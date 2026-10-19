import assert from "node:assert/strict";
import test from "node:test";
import { SECTOR_COLUMNS, sectorSnapshot, sectors } from "../src/sectors.js";
import { handle } from "../src/worker.js";
const now = new Date("2026-10-20T00:00:00Z");
const row = (fields = {}) => ({ s: `KRX:${fields.name ?? "005930"}`, d: SECTOR_COLUMNS.map(key => ({ name: "005930", description: "삼성전자보통주", exchange: "KRX", type: "stock", subtype: "common", sector: "Electronic Technology", industry: "Semiconductors", close: 100, change: 0, "Value.Traded": 2e12, market_cap_basic: 5e14, currency: "KRW", time: Date.parse("2026-10-19T00:00:00Z") / 1000, indexes: [{ proname: "KRX:KOSPI" }], "Perf.W": 2, "Perf.1M": -3, "Perf.3M": 4, "Perf.Y": 50, ...fields })[key] ?? null) });
const payload = (...data) => ({ totalCount: data.length, data });
const json = body => new Response(JSON.stringify(body), { headers: { "Content-Type": "application/json" } });

test("KRW native units, listing identity and zero returns survive sector collection", () => {
  const data = sectorSnapshot(payload(row(), row({ name: "000660", indexes: [{ proname: "KRX:KOSDAQ" }], "Value.Traded": null, "Perf.W": null })), now);
  const samsung = data.stocks.find(stock => stock.code === "005930");
  assert.equal(samsung.ticker, "005930.KS"); assert.equal(samsung.name, "삼성전자");
  assert.equal(samsung.turnover, 2e12); assert.equal(samsung.market_cap, 5e14); assert.equal(samsung.returns.day, 0);
  assert.equal(data.stocks[0].ticker, "000660.KQ"); assert.equal(data.stocks[0].turnover, null); assert.equal(data.stocks[0].returns.week, null);
  assert.equal(data.date, "2026-10-19"); assert.equal(data.stale_count, 0);
});
test("old bars are identifiable and non-equities, non-KRX, non-KRW and unknown boards cannot enter totals", () => {
  const data = sectorSnapshot(payload(row(), row({ name: "000660", time: Date.parse("2026-10-16T00:00:00Z") / 1000 }), row({ name: "123456", subtype: "preferred" }), row({ name: "123457", currency: "USD" }), row({ name: "123458", indexes: [] }), row({ name: "123459", close: null })), now);
  assert.equal(data.stocks.length, 2); assert.equal(data.stale_count, 1);
  assert.deepEqual(data.excluded, { unsupported_listing: 2, other_currency: 1, missing_price: 1 });
});
test("incomplete, duplicate, contradictory and future source responses fail rather than publish a misleading ranking", () => {
  assert.throws(() => sectorSnapshot({ totalCount: 6001, data: [row()] }, now));
  assert.throws(() => sectorSnapshot(payload(row(), row()), now));
  assert.throws(() => sectorSnapshot(payload(row({ indexes: [{ proname: "KRX:KOSPI" }, { proname: "KRX:KOSDAQ" }] })), now));
  assert.throws(() => sectorSnapshot(payload(row({ time: Date.parse("2026-10-22T00:00:00Z") / 1000 })), now));
  assert.throws(() => sectorSnapshot(payload({ s: "KRX:005930", d: [1] }), now));
});
test("each refresh is one uncached whole-market scan with preferred shares excluded and native KRW requested", async () => {
  let calls = 0;
  for (let i = 0; i < 2; i++) await sectors(async (url, options) => {
    calls++; assert.equal(new URL(url).hostname, "scanner.tradingview.com");
    const body = JSON.parse(options.body);
    assert.ok(body.filter.some(item => item.left === "subtype" && item.right === "common"));
    assert.equal(body.options.price_conversion.to_symbol, true); assert.deepEqual(body.range, [0, 6000]);
    assert.equal(options.cf.cacheTtl, 0); return json(payload(row()));
  });
  assert.equal(calls, 2);
});
test("sector endpoint shares existing CORS and sanitized failure handling", async () => {
  const request = origin => new Request("https://api.example/refresh", { method: "POST", headers: { Origin: origin, "Content-Type": "application/json" }, body: JSON.stringify({ kind: "sectors" }) });
  const ok = await handle(request("https://juyeop-dev.github.io"), {}, async () => json(payload(row())));
  assert.equal(ok.status, 200); assert.equal((await ok.json()).stocks[0].ticker, "005930.KS");
  assert.ok(ok.headers.get("Cache-Control").includes("no-store"));
  assert.equal((await handle(request("https://other.example"), {}, () => { throw new Error("Should not query"); })).status, 403);
  const failed = await handle(request("https://juyeop-dev.github.io"), {}, async () => json({ totalCount: 2, data: [row()] }));
  assert.equal(failed.status, 502); assert.ok((await failed.json()).error.includes("기존 값은 유지"));
});
