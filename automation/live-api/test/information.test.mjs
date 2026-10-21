import test from "node:test";
import assert from "node:assert/strict";
import { reportedFinancials, naverStatements, information } from "../src/information.js";

test("reported financials preserve native reporting currency, reject wrong listing, forecasts and YTD", () => {
  const item = (day, periodType, raw) => ({asOfDate: day, periodType, currencyCode: "TWD", reportedValue: {raw}});
  const payload = {timeseries: {result: [{meta: {symbol: ["2330.TW"]}, quarterlyTotalRevenue: [item("2025-03-31", "3M", 0), item("2026-12-31", "3M", 10), item("2025-06-30", "6M", 20)]}]}};
  assert.deepEqual(reportedFinancials(payload, "2330.TW", "2026-10-20").map(row => [row.period_end, row.currency, row.revenue]), [["2025-03-31", "TWD", 0]]);
  assert.throws(() => reportedFinancials(payload, "TSM", "2026-10-20"), /일치/);
});
test("domestic reported statements convert eok, preserve losses and exclude estimates", () => {
  const payload = {financeInfo: {trTitleList: [{key:"202512",isConsensus:"N"},{key:"202612",isConsensus:"Y"}], rowList:[{title:"매출액",columns:{202512:{value:"1,234.5"}}},{title:"영업이익",columns:{202512:{value:"-5"}}}]}};
  const [row] = naverStatements(payload, "annual", "2026-10-20");
  assert.equal(row.revenue, 123450000000); assert.equal(row.operating_income, -500000000); assert.equal(row.currency,"KRW");
});
test("manual information refresh requests both current fundamentals and historical reported statements", async () => {
  const calls = [];
  const result = await information({ticker:"AAPL",exchange:"NASDAQ"}, async (url, init) => {
    calls.push(url);
    if (url.includes("scanner.tradingview.com")) {
      const body = JSON.parse(init.body);
      assert.equal(body.price_conversion.to_symbol, true);
      const values = {description:"Apple",close:100,change:0,currency:"USD",time:Date.now()/1000, fundamental_currency_code:"USD"};
      return Response.json({data:[{s:"NASDAQ:AAPL",d:body.columns.map(column => values[column] ?? null)}]});
    }
    return Response.json({timeseries:{result:[{meta:{symbol:["AAPL"]},annualTotalRevenue:[{asOfDate:"2025-09-30",periodType:"12M",currencyCode:"USD",reportedValue:{raw:1000}}]}]}});
  });
  assert.equal(calls.length,4); assert.ok(calls[1].includes("period1=1719792000")); assert.ok(calls.some(url=>url.includes("period2=1767225600"))); assert.ok(calls.some(url=>url.includes("period2=1735689600"))); assert.equal(result.financials[0].revenue,1000); assert.equal(result.quote.price,100);
});
