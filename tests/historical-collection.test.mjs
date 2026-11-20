import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp, mkdir, readFile, writeFile, rm} from 'node:fs/promises';
import {join, dirname} from 'node:path';
import {tmpdir} from 'node:os';
import {verifiedSessions} from '../shared/trading-sessions.mjs';
import {collectionRequest, collectionArgs, ROOT} from '../scripts/collection-request.mjs';
import {collectInvestorHistory} from '../scripts/backfill_investors.mjs';
import {parseInvestorFlow} from '../automation/live-api/src/investors.js';

const originalCalendar = JSON.parse(await readFile(join(ROOT, 'data/market-closures/2014.json'), 'utf8'));
const flow = date => parseInvestorFlow({bizdate: date.replaceAll('-', ''), netAmounts: ['8000', '9000', '1000', '7100'].map(code =>
  ({investorGubun: code, buyPrice: 100, sellPrice: 100, diffValue: 0}))});
const index = date => ({date, close: 100, open: 99, high: 101, low: 98});

async function fixture(callback) {
  const root = await mkdtemp(join(tmpdir(), 'history-investors-'));
  try {
    const calendar = join(root, 'data/market-closures/2014.json');
    await mkdir(dirname(calendar), {recursive: true}); await writeFile(calendar, JSON.stringify(originalCalendar));
    const source = join(root, 'data/investors/index.json');
    await mkdir(dirname(source), {recursive: true});
    const previous = {requested_start: '2010-01-01', unit: 'KRW', history: [
      {date: '2014-01-02', original: 123.123456789}, {date: '2015-01-02', original: 'later record'}]};
    await writeFile(source, JSON.stringify(previous));
    const request = {...await collectionRequest({year: 2014, root}), start: '2014-01-02', end: '2014-01-03'};
    await callback({root, source, previous, request});
  } finally { await rm(root, {recursive: true, force: true}); }
}

test('verified calendar retains official Saturday opening and typhoon closure', () => {
  const days = verifiedSessions('2014-01-01', '2014-12-31', 'taiwan', {2014: originalCalendar});
  assert.equal(days.length, 248);
  assert.ok(days.includes('2014-12-27'));
  assert.ok(!days.includes('2014-07-23'));
  assert.equal(verifiedSessions('2014-01-01', '2014-12-31', 'korea', {2014: originalCalendar}).length, 245);
  assert.throws(() => verifiedSessions('2013-01-01', '2013-12-31', 'korea', {}), /calendar missing/);
});

test('request CLI validates years and retains exact policy path', async () => {
  assert.throws(() => collectionArgs(['--year', '2013x']), /Invalid year/);
  assert.throws(() => collectionArgs(['--history-config']), /Missing argument/);
  assert.throws(() => collectionArgs(['--unknown']), /Unknown argument/);
  const request = await collectionRequest({year: 2013, asOf: '2026-11-18'});
  assert.equal(request.start, '2013-01-01'); assert.equal(request.end, '2013-12-31');
  assert.match(request.state, /tmp_2013$/);
});

test('exact date pairs preserve existing earlier and later records and reuse caches', async () => fixture(async ({root, source, previous, request}) => {
  let calls = 0;
  const dates = ['2014-01-03', '2014-01-02', '2013-12-31'];
  const dependencies = {flowPage: async () => { calls++; return dates.map(flow); },
    indexPage: async () => { calls++; return dates.map(index); }, now: new Date('2026-11-18T10:00:00Z')};
  const value = await collectInvestorHistory(request, dependencies);
  assert.equal(calls, 4);
  assert.equal(value.requested_start, '2010-01-01');
  for (const record of previous.history) assert.deepEqual(value.history.find(row => row.date === record.date), record);
  const added = value.history.find(row => row.date === '2014-01-03');
  assert.equal(added.markets.length, 2);
  assert.ok(added.markets.every(row => row.date === row.index.date));
  assert.deepEqual(JSON.parse(await readFile(join(root, 'frontend/public/data/investors/index.json'), 'utf8')), value);
  await collectInvestorHistory(request, dependencies);
  assert.equal(calls, 4);
  assert.equal(JSON.parse(await readFile(source, 'utf8')).history.length, 3);
}));

test('missing exact index fails before changing source or publishing partial pairs', async () => fixture(async ({source, request}) => {
  const before = await readFile(source);
  await assert.rejects(collectInvestorHistory(request, {flowPage: async () => ['2014-01-03', '2014-01-02', '2013-12-31'].map(flow),
    indexPage: async () => ['2014-01-02', '2013-12-31'].map(index)}), /Missing exact index/);
  assert.deepEqual(await readFile(source), before);
}));

test('unverified year fails before provider access', async () => fixture(async ({request}) => {
  let called = false;
  await assert.rejects(collectInvestorHistory({...request, start: '2013-01-01', end: '2013-12-31'}, {
    flowPage: async () => { called = true; return []; }, indexPage: async () => { called = true; return []; }}), /ENOENT/);
  assert.equal(called, false);
}));

test('duplicate source dates cannot become apparently complete coverage', async () => fixture(async ({source, request}) => {
  const before = await readFile(source);
  await assert.rejects(collectInvestorHistory(request, {flowPage: async () => ['2014-01-03', '2014-01-03', '2013-12-31'].map(flow),
    indexPage: async () => ['2014-01-03', '2014-01-02', '2013-12-31'].map(index)}), /Repeated source date/);
  assert.deepEqual(await readFile(source), before);
}));

test('partial-year cache does not hide a later requested endpoint', async () => fixture(async ({request}) => {
  let calls = 0;
  const dependencies = end => ({flowPage: async () => { calls++; return [end, ...(end === '2014-01-03' ? [] : ['2014-01-03']), '2014-01-02', '2013-12-31'].map(flow); },
    indexPage: async () => { calls++; return [end, ...(end === '2014-01-03' ? [] : ['2014-01-03']), '2014-01-02', '2013-12-31'].map(index); }});
  await collectInvestorHistory(request, dependencies('2014-01-03'));
  const value = await collectInvestorHistory({...request, end: '2014-01-06'}, dependencies('2014-01-06'));
  assert.equal(calls, 8);
  assert.ok(value.history.some(row => row.date === '2014-01-06'));
}));

test('cached boundary-only rows never become investor amounts', async () => fixture(async ({source, request}) => {
  const before = await readFile(source);
  await assert.rejects(collectInvestorHistory(request, {flowPage: async () => [{date: '2014-01-03'}, flow('2014-01-02'), {date: '2013-12-31'}],
    indexPage: async () => ['2014-01-03', '2014-01-02', '2013-12-31'].map(index)}), /Invalid cached investor/);
  assert.deepEqual(await readFile(source), before);
}));
