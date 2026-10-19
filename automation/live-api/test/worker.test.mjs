import assert from "node:assert/strict";
import test from "node:test";
import { handle } from "../src/worker.js";
import { naverFinancialRows, recentFinancials, scan, wonAmount, yahooData } from "../src/providers.js";
const json = value => new Response(JSON.stringify(value), { headers: { "Content-Type": "application/json" } });
const request = (body, origin = "https://juyeop-dev.github.io") => new Request("https://api.example/refresh", { method: "POST", headers: { "Content-Type": "application/json", Origin: origin }, body: JSON.stringify(body) });

test("requests reach the original provider on every click and are never served from a response cache", async () => {
  const calls = [];
  const fetcher = async (url, options) => {
    calls.push({ url, options });
    if (url.includes("tradingview")) return json({ data: [{ d: [101000, -1.2, "KRW", 900e9, 1792411200, "회사", "USD"] }] });
    return json(url.includes("integration") ? { totalInfos: [{ code: "marketValue", value: "1조 2,345억" }] }
      : { closePrice: "101,000", fluctuationsRatio: "-1.2", compareToPreviousClosePrice: "1,200", localTradedAt: "2026-10-19T15:30:00+09:00" });
  };
  for (let i = 0; i < 2; i++) {
    const result = await handle(request({ kind: "quotes", stocks: [{ ticker: "000660.KS" }] }), {}, fetcher);
    const data = await result.json();
    assert.equal(result.status, 200);
    assert.equal(result.headers.get("Access-Control-Allow-Origin"), "https://juyeop-dev.github.io");
    assert.ok(result.headers.get("Cache-Control").includes("no-store"));
    assert.equal(data.items[0].price, 101000);
    assert.equal(data.items[0].change, -1200);
    assert.equal(data.items[0].previous_close, 102200);
    assert.equal(data.items[0].market_cap, 1234500000000);
  }
  assert.equal(calls.length, 6);
  assert.equal(calls.every(call => call.options.cf.cacheTtl === 0 && call.options.headers["Cache-Control"] === "no-cache"), true);
});
test("provider failures report failure instead of claiming that retained data is fresh", async () => {
  const failed = await handle(request({ kind: "quotes", stocks: [{ ticker: "AAPL" }] }), {}, async () => { throw new Error("internal secret URL"); });
  assert.equal(failed.status, 502);
  const data = await failed.json();
  assert.deepEqual(data.items, []);
  assert.equal(data.errors[0].ticker, "AAPL");
  assert.equal(JSON.stringify(data).includes("secret"), false);
});
test("origin checks and ticker validation happen before any upstream request", async () => {
  let calls = 0;
  const fetcher = async () => { calls++; return json({}); };
  assert.equal((await handle(request({ kind: "quotes", stocks: [{ ticker: "AAPL" }] }, "https://other.example"), {}, fetcher)).status, 403);
  assert.equal((await handle(request({ kind: "quotes", stocks: [{ ticker: "https://internal.example" }] }), {}, fetcher)).status, 400);
  assert.equal((await handle(request({ kind: "details", stocks: Array(5).fill({ ticker: "AAPL" }) }), {}, fetcher)).status, 400);
  assert.equal(calls, 0);
});
test("Yahoo's previous close is the previous trading day, never the start of a two-year chart", async () => {
  const data = await yahooData("AAPL", async () => json({ chart: { result: [{
    meta: { regularMarketPrice: 120, regularMarketTime: 1792411200, chartPreviousClose: 10, currency: "USD", exchangeTimezoneName: "UTC" },
    timestamp: [1792152000, 1792411200], indicators: { quote: [{ close: [100, 120], volume: [5, 8] }], adjclose: [{ adjclose: [95, 120] }] },
  }] } }), true);
  assert.equal(data.quote.previous_close, 100);
  assert.ok(Math.abs(data.quote.change_pct - 20) < 1e-9);
  assert.equal(data.history[0].adjusted_close, 95);
});
test("financial refresh excludes estimates and only sums four consecutive actual quarters", () => {
  const rows = naverFinancialRows({ financeInfo: { trTitleList: [{ key: "a", title: "2026.06", isConsensus: "N" }, { key: "b", title: "2026.09", isConsensus: "Y" }],
    rowList: [{ title: "매출액", columns: { a: { value: "100" }, b: { value: "900" } } }] } }, "quarterly");
  assert.equal(rows.length, 1);
  assert.equal(rows[0].revenue, 100);
  const quarters = ["2025.09", "2025.12", "2026.03", "2026.06"].map(period => ({ period, revenue: 100, operating_income: 10, type: "quarterly" }));
  assert.equal(recentFinancials(quarters, []).revenue, 400);
  assert.equal(recentFinancials(quarters.slice(1), [{ period: "2025.12", revenue: 300, operating_income: 20 }]).basis, "annual");
  assert.equal(wonAmount("12,345억"), 1234500000000);
});

test("new-high scans filter upstream, deduplicate thresholds and use the latest traded session independently", async () => {
  const stamp = Date.parse("2026-10-19T00:00:00Z") / 1000;
  const row = ["1234", "Company", "TSE", "stock", "Technology", "Electronics", 90, 100, 99, 10,
    100, 100, stamp, "JPY", 9000000, 1000, [], "USD"];
  const requests = [];
  const result = await scan("japan", "new-highs", async (url, options) => {
    const body = JSON.parse(options.body); requests.push(body);
    if (body.columns.length === 2) return json({ data: [{ d: [stamp, "TSE"] }] });
    return json({ totalCount: 2, data: [{ s: "TSE:1234", d: row }, { s: "TSE:5678", d: row.map((value, i) => i === 0 ? "5678" : i === 12 ? stamp - 86400 * 3 : value) }] });
  });
  assert.equal(requests.length, 3);
  assert.ok(requests.every(body => body.filter.some(filter => filter.left === "time" && filter.operation === "eless")));
  assert.deepEqual(requests.slice(0, 2).map(body => body.filter.find(filter => filter.left === "high").right), ["price_52_week_high", "High.All"]);
  assert.equal(result.date, "2026-10-19");
  assert.equal(result.entries.length, 1);
  assert.equal(result.entries[0].high_type, "all_time");
  assert.equal(result.entries[0].currency, "JPY");
  assert.equal(result.entries[0].market_cap_currency, "USD");
  const empty = await scan("japan", "new-highs", async (url, options) => {
    const body = JSON.parse(options.body);
    return json(body.columns.length === 2 ? { data: [{ d: [stamp, "TSE"] }] } : { totalCount: 0, data: [] });
  });
  assert.equal(empty.date, "2026-10-19");
  assert.deepEqual(empty.entries, []);
});
