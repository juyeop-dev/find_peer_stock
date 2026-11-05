import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import ts from 'typescript';

const source = await readFile(new URL('../src/dataClient/chartReplay.ts', import.meta.url), 'utf8');
const javascript = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText;
const { aggregateReplay, hasOHLC, replayAverage, replayRange, replayReturns, validateReplayMarket, validReplayDate } = await import(`data:text/javascript;base64,${Buffer.from(javascript).toString('base64')}`);
const bar = (date, close, extra = {}) => ({ date, close, adjusted_close: close, volume: null, ...extra });
const { initialReplaySettings, restoreReplaySettings } = await import(`data:text/javascript;base64,${Buffer.from(javascript).toString('base64')}`);

test('stock replay defaults to a full one-year return overlay with matching dates and no unrelated gold preset', () => {
  const value = initialReplaySettings('MU', 'Micron', 'NASDAQ', new Date('2024-02-29T16:00:00Z'));
  assert.equal(value.overlay, true);
  assert.equal(value.count, null);
  assert.equal(value.autoPeer, true);
  assert.equal(value.selections[0].start, '2023-03-01');
  assert.equal(value.selections[0].end, '2024-03-01');
  assert.equal(value.selections[1].ticker, '');
  assert.equal(value.selections[1].start, value.selections[0].start);
  assert.equal(initialReplaySettings(undefined).overlay, false);
  assert.equal(initialReplaySettings(undefined).selections[1].ticker, 'GC=F');
  assert.equal(initialReplaySettings('MU', '', '', new Date('2024-02-29T00:00:00Z')).selections[0].start, '2023-02-28');
});

test('legacy gold defaults migrate to peer selection while intentional saved comparisons and new layout preferences survive', () => {
  const fallback = initialReplaySettings('MU', 'Micron');
  const stock = { ticker: 'MU', name: 'Micron', start: '2025-01-01', end: '2026-12-31' };
  const legacy = { version: 1, selections: [stock, { ticker: 'GC=F', name: 'Gold', start: '2024-01-01', end: '2024-12-31' }], overlay: false, count: 25 };
  const restored = restoreReplaySettings(JSON.stringify(legacy), fallback, true);
  assert.equal(restored.selections[1].ticker, '');
  assert.equal(restored.selections[1].start, stock.start);
  assert.equal(restored.overlay, true);
  assert.equal(restored.count, null);
  assert.equal(restored.autoPeer, true);
  const manual = { ...legacy, selections: [stock, { ...stock, ticker: 'AMD', name: 'AMD' }], count: 40 };
  assert.equal(restoreReplaySettings(JSON.stringify(manual), fallback, true).selections[1].ticker, 'AMD');
  assert.equal(restoreReplaySettings(JSON.stringify(manual), fallback, true).autoPeer, false);
  const saved = restoreReplaySettings(JSON.stringify({ ...manual, version: 2 }), fallback, true);
  assert.equal(saved.overlay, false);
  assert.equal(saved.count, 40);
  assert.equal(restoreReplaySettings('{broken', fallback, true), fallback);
  assert.equal(restoreReplaySettings(JSON.stringify({ ...manual, selections: [null, null] }), fallback, true), fallback);
});
const market = bars => ({ ticker: 'TEST', name: 'Test', currency: 'USD', source: 'Test provider', bars });

test('date ranges reject impossible/reversed dates and do not invent holiday observations', () => {
  assert.equal(validReplayDate('2024-02-29'), true);
  for (const value of ['2022-02-29', '2024-02-30', '2024-13-01', '', '2022-1-1']) assert.equal(validReplayDate(value), false);
  const rows = [bar('2022-01-03', 100), bar('2022-01-05', 110), bar('2022-01-06', 120)];
  assert.deepEqual(replayRange(rows, '2022-01-01', '2022-01-05'), rows.slice(0, 2));
  assert.deepEqual(replayRange(rows, '2021-01-01', '2021-12-31'), []);
  assert.throws(() => replayRange(rows, '2022-02-01', '2022-01-01'));
});

test('weekly and monthly replay aggregates contain no high/low/close/volume from hidden future sessions', () => {
  const rows = [bar('2024-01-02', 100, { open: 99, high: 101, low: 98, volume: 10 }), bar('2024-01-03', 110, { open: 100, high: 112, low: 100, volume: 20 }), bar('2024-01-04', 999, { open: 110, high: 1000, low: 1, volume: 9000 })];
  for (const interval of ['week', 'month']) {
    const visible = aggregateReplay(rows.slice(0, 2), interval);
    assert.deepEqual(visible, [bar('2024-01-02', 110, { open: 99, high: 112, low: 98, volume: 30 })]);
    assert.equal(aggregateReplay(rows, interval)[0].high, 1000);
  }
  assert.equal(replayAverage(rows.slice(0, 2), 2)[0].value, 105);
  assert.equal(replayReturns(rows.slice(0, 2)).at(-1).value.toFixed(2), '10.00');
});

test('aggregation handles year/week boundaries, missing volumes and close-only histories without fabricating candles', () => {
  const rows = [bar('2023-12-29', 100), bar('2024-01-02', 101), bar('2024-01-03', 102)];
  assert.deepEqual(aggregateReplay(rows, 'week').map(row => row.date), ['2023-12-29', '2024-01-02']);
  assert.equal(aggregateReplay(rows, 'month')[1].close, 102);
  assert.equal(aggregateReplay(rows, 'month')[1].volume, null);
  assert.equal(hasOHLC(aggregateReplay(rows, 'month')[1]), false);
});

test('returns align by actual session index with independent dates and use adjusted close across splits', () => {
  const a = replayReturns([bar('2022-01-03', 100), bar('2022-01-04', 50, { adjusted_close: 100 }), bar('2022-01-05', 55, { adjusted_close: 110 })]);
  const b = replayReturns([bar('2024-01-02', 200), bar('2024-01-04', 220)]);
  assert.equal(a[1].value, 0);
  assert.equal(a[2].value.toFixed(2), '10.00');
  assert.deepEqual(a.slice(0, 2).map(row => row.session), b.map(row => row.session));
  assert.notEqual(a[1].date, b[1].date);
});

test('untrusted data rejects duplicate dates, invalid prices, OHLC and volumes', () => {
  assert.doesNotThrow(() => validateReplayMarket(market([bar('2024-01-02', 100)])));
  for (const rows of [[bar('2024-02-30', 100)], [bar('2024-01-02', NaN)], [bar('2024-01-02', 100, { adjusted_close: 0 })], [bar('2024-01-02', 100, { volume: -1 })], [bar('2024-01-02', 100, { open: 100, high: 99, low: 98 })], [bar('2024-01-02', 100, { open: 100 })], [bar('2024-01-02', 100), bar('2024-01-02', 110)]]) assert.throws(() => validateReplayMarket(market(rows)));
});

test('retained real data supports the requested KOSPI 2022 and gold 2024 example with source identity', async () => {
  const snapshot = JSON.parse(await readFile(new URL('../public/data/chart-replay/markets.json', import.meta.url), 'utf8'));
  assert.equal(snapshot.schema_version, 1);
  for (const [ticker, year, currency] of [['^KS11', '2022', 'KRW'], ['GC=F', '2024', 'USD']]) {
    const row = snapshot.markets.find(row => row.ticker === ticker);
    validateReplayMarket(row);
    assert.equal(row.currency, currency);
    assert.ok(row.source.includes(ticker));
    const selected = replayRange(row.bars, `${year}-01-01`, `${year}-12-31`);
    assert.ok(selected.length >= 240, `${ticker}: insufficient real history`);
    assert.ok(selected.every(hasOHLC));
    assert.equal(replayReturns(selected)[0].value, 0);
    if (ticker === '^KS11') assert.equal(selected[0].date, '2022-01-03', 'KOSPI must include the first actual 2022 session');
  }
});
