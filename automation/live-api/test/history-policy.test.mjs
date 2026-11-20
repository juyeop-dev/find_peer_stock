import test from 'node:test';
import assert from 'node:assert/strict';
import policy from '../../../config/history-policy.json' with {type: 'json'};
import {collectionHistory, publishedHistoryStart, historyWindow} from '../src/history-policy.js';
import {information, reportedFinancials, MAX_FINANCIAL_WINDOWS} from '../src/information.js';
import {history} from '../src/history.js';

test('an earlier collection goal cannot advance verified publication or API investor choices', () => {
  const earlier = structuredClone(policy); earlier.collection.start_year = 2013;
  const range = collectionHistory('2026-11-18', earlier);
  assert.equal(range.start_date, '2013-01-01'); assert.equal(range.price_reference_start, '2012-12-20');
  assert.equal(publishedHistoryStart('stock_history'), '2014-01-01');
  assert.equal(publishedHistoryStart('investors'), '2014-01-01');
});

test('bounded requests keep their original price dates, exclusive endpoint and source identity', async () => {
  const value = structuredClone(policy); Object.assign(value.collection, {start_year: 2013, end_year: 2013});
  const range = collectionHistory('2026-11-18', value), requests = [];
  const rows = ['2013-01-02', '2013-12-31', '2014-01-02'];
  const result = await history({ticker: 'TEST'}, async url => {
    requests.push(url);
    return Response.json({chart: {result: [{meta: {symbol: 'TEST', instrumentType: 'EQUITY', currency: 'USD', exchangeTimezoneName: 'UTC'},
      timestamp: rows.map(day => Date.parse(`${day}T12:00:00Z`) / 1000), indicators: {quote: [{close: [10, 11, 12]}]}}]}});
  }, range);
  assert.equal(new URL(requests[0]).searchParams.get('period2'), String(Date.parse('2014-01-01') / 1000));
  assert.deepEqual(result.history.map(row => row.date), rows.slice(0, 2));
  assert.ok(historyWindow(range).startDate <= '2012-12-20');
});

test('financial source windows follow the configured year while observed zero and losses survive', async () => {
  const value = structuredClone(policy); value.collection.start_year = 2013;
  const range = collectionHistory(undefined, value), calls = [];
  const result = await information({ticker: 'AAPL'}, async (url, init) => {
    calls.push(url);
    if (url.includes('scanner.tradingview.com')) {
      const body = JSON.parse(init.body), values = {description: 'Fixture', fundamental_currency_code: 'USD', market_cap_basic: 100};
      return Response.json({data: [{s: 'NASDAQ:AAPL', d: body.columns.map(key => values[key] ?? null)}]});
    }
    const stamp = Number(new URL(url).searchParams.get('period2')) * 1000;
    const year = Math.min(new Date().getUTCFullYear() - 1, new Date(stamp - 1000).getUTCFullYear());
    return Response.json({timeseries: {result: [{meta: {symbol: ['AAPL']}, annualTotalRevenue: [
      {asOfDate: `${year}-12-31`, periodType: '12M', currencyCode: 'USD', reportedValue: {raw: 0}}]}]}});
  }, range);
  assert.ok(calls.some(url => url.includes('period1=1356998400')));
  assert.equal(result.historical_2013_coverage.start, '2013-01-01');
  assert.equal(result.financials.find(row => row.period_end === '2013-12-31').revenue, 0);
  const payload = {timeseries: {result: [{meta: {symbol: ['AAPL']}, quarterlyOperatingIncome: [
    {asOfDate: '2013-03-31', periodType: '3M', currencyCode: 'TWD', reportedValue: {raw: -7}}]}]}};
  assert.equal(reportedFinancials(payload, 'AAPL', range.end_date, range)[0].operating_income, -7);
});

test('source window limits remain explicit instead of unbounded per-year provider requests', async () => {
  const value = structuredClone(policy); value.collection.start_year = 1970;
  let calls = 0;
  const result = await information({ticker: 'AAPL'}, async (url, init) => {
    calls++;
    if (url.includes('scanner.tradingview.com')) {
      const body = JSON.parse(init.body), values = {description: 'Fixture', fundamental_currency_code: 'USD', market_cap_basic: 100};
      return Response.json({data: [{s: 'NASDAQ:AAPL', d: body.columns.map(key => values[key] ?? null)}]});
    }
    return Response.json({timeseries: {result: []}});
  }, collectionHistory(undefined, value));
  assert.equal(calls, MAX_FINANCIAL_WINDOWS + 2);
  assert.ok(result.warnings.some(value => value.includes('저장된 자료')));
});
