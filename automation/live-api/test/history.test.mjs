import test from "node:test";
import assert from "node:assert/strict";
import { decodeFrames, history, tradingViewHistory } from "../src/history.js";

const frame = (m, p) => { const body = JSON.stringify({ m, p }); return `~m~${body.length}~m~${body}`; };
const yahoo = symbol => ({ chart: { result: [{ meta: { symbol, instrumentType: "EQUITY", currency: "USD", exchangeTimezoneName: "America/New_York", regularMarketPrice: 120,
  regularMarketTime: 1792177200, firstTradeDate: 345479400 }, timestamp: [1758211200, 1792177200], indicators: { quote: [{ close: [100, 120], volume: [10, 20] }] } }] } });

test("history requests the exact Yahoo listing from at least July 2024 and two calendar years", async () => {
  const urls = [];
  const result = await history({ ticker: "AAPL" }, async url => { urls.push(url); return Response.json(yahoo("AAPL")); });
  assert.equal(result.ticker, "AAPL");
  assert.equal(result.history.length, 2);
  assert.ok(result.history[0].date < "2025-10-01");
  assert.ok(Number(new URL(urls[0]).searchParams.get("period1")) <= Date.parse("2024-07-01T00:00:00Z") / 1000);
  assert.equal(result.currency, "USD");
});

class FakeChart extends EventTarget {
  constructor(wrong = false, cboe = false) { super(); this.wrong = wrong; this.cboe = cboe; }
  accept() {}
  close() {}
  send(raw) {
    const { m, p } = JSON.parse(decodeFrames(raw)[0]);
    if (m !== "create_series") return;
    queueMicrotask(() => {
      const session = p[0];
      const info = this.cboe ? {pro_name:"NYSE:EP/PC",name:"EP/PC",full_name:"BATS:EP/PC",source_id:"BATS",type:"stock",currency_code:"USD",timezone:"America/New_York"} : { pro_name: this.wrong ? "EURONEXT:OTHER" : "EURONEXT:MC", source_id: "EURONEXT", type: "stock", currency_code: "EUR", timezone: "Europe/Paris" };
      const data = frame("symbol_resolved", [session, "symbol_1", info]) + frame("timescale_update", [session, { s1: { s: [
        { v: [1758211200, 90, 110, 80, 100, 1] }, { v: [1792177200, 100, 130, 90, 120, 2] },
      ] } }]) + frame("series_completed", [session, "s1"]);
      this.dispatchEvent(new MessageEvent("message", { data }));
    });
  }
}
test("European histories use the same TradingView symbol and reject a substituted listing", async () => {
  const result = await tradingViewHistory({ ticker: "EURONEXT:MC" }, async () => ({ webSocket: new FakeChart() }));
  assert.equal(result.currency, "EUR");
  assert.equal(result.history.length, 2);
  await assert.rejects(() => tradingViewHistory({ ticker: "EURONEXT:MC" }, async () => ({ webSocket: new FakeChart(true) })), /일치/);
});
test("TradingView framing handles non-ASCII descriptions without corrupting the next message", () => {
  const values = decodeFrames(frame("one", ["고영 ® 😀"]) + frame("two", []));
  assert.equal(JSON.parse(values[0]).p[0], "고영 ® 😀");
  assert.equal(JSON.parse(values[1]).m, "two");
  assert.throws(() => decodeFrames("~m~100~m~short"));
});
test("same US security on the documented Cboe feed is labelled instead of presented as primary-exchange data", async () => {
  const result = await tradingViewHistory({ticker:"EP/PC",exchange:"NYSE"}, async () => ({webSocket:new FakeChart(false,true)}));
  assert.match(result.source,/Cboe One/);
  assert.equal(result.currency,"USD");
});
