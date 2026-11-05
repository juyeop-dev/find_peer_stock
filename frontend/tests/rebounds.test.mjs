import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import ts from 'typescript';
const source = await readFile(new URL('../src/dataClient/reboundClient.ts', import.meta.url), 'utf8');
const js = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText;
const { REBOUND_RULES, validateReboundReport, reboundEntries, reboundMessage, validReboundDate } = await import(`data:text/javascript;base64,${Buffer.from(js).toString('base64')}`);
const stock = (ticker, name, exchange, price, low, cap, change_pct = 0) => ({ ticker, name, exchange, price, low, market_cap: cap, change_pct, rebound_pct: (price / low - 1) * 100, currency: 'KRW', market_cap_currency: 'KRW', sector: '', industry: '' });
const report = { schema_version: 1, market: 'korea', date: '2026-11-02', rules: REBOUND_RULES, sources: [], source_metadata: { session: 'daily', fetched_at: '2026-11-02T07:00:00Z', scanned_symbols: 2638 }, entries: [stock('009830.KS', '한화솔루션', 'KOSPI', 108, 100, 5e12), stock('039030.KQ', '이오테크닉스', 'KOSDAQ', 105, 100, 1e12), stock('006400.KS', '삼성SDI', 'KOSPI', 110, 100, 5e12, 1)] };
test('validates inclusive thresholds, preserves flat stocks and sorts and searches within each board', () => {
  assert.equal(validateReboundReport(report, report.date), report);
  assert.deepEqual(reboundEntries(report, 'KOSPI').map(row => row.name), ['삼성SDI', '한화솔루션']);
  assert.equal(reboundEntries(report, 'KOSPI', '한화').length, 1);
  assert.equal(reboundEntries(report, 'KOSDAQ', '039030')[0].ticker, '039030.KQ');
});
test('rejects wrong dates, declines, invalid prices, small caps, tampered rates and duplicate or wrong listings', () => {
  assert.throws(() => validateReboundReport(report, '2026-11-03'));
  for (const change of [{ change_pct: -.01 }, { low: 0 }, { price: 99 }, { market_cap: 5e12 - 1 }, { rebound_pct: 99 }, { ticker: '009830.KQ' }]) {
    assert.throws(() => validateReboundReport({ ...report, entries: [{ ...report.entries[0], ...change }] }, report.date));
  }
  assert.throws(() => validateReboundReport({ ...report, entries: [report.entries[0], report.entries[0]] }, report.date));
  assert.throws(() => validateReboundReport({ ...report, source_metadata: undefined }, report.date));
  assert.throws(() => validateReboundReport({ ...report, rules: {} }, report.date));
});
test('copy format matches the requested report with calculated counts, dates, price and separate daily change', () => {
  const text = reboundMessage(report);
  assert.ok(text.startsWith('🇰🇷 2026.11.02(월) 📊 국내 대형주 반등'));
  assert.ok(text.includes('KOSPI 2개 | 시총 5조 이상 | 반등 8% 이상'));
  assert.ok(text.includes('🔴 KOSDAQ (1)'));
  assert.ok(text.includes('• 한화솔루션 +8.00% | 108원 (+0.00%)'));
  assert.ok(text.indexOf('• 삼성SDI') < text.indexOf('• 한화솔루션'));
  assert.ok(reboundMessage({ ...report, entries: [] }).includes('조건에 맞는 종목이 없습니다.'));
});
test('invalid calendar dates and malformed date inputs are not accepted as archive paths', () => {
  for (const date of [null, '', '../index', '2026-02-30', '2026-13-02', '2026-1-2']) assert.equal(validReboundDate(date), false);
  assert.equal(validReboundDate('2024-02-29'), true);
});
