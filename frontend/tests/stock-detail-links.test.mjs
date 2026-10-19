import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const seeds = JSON.parse(await readFile(new URL("../../data/seed/semiconductor_stocks.json", import.meta.url), "utf8"));
const source = (await readFile(new URL("../src/dataClient/stockDetailLinks.ts", import.meta.url), "utf8"))
  .replace(/^import semiconductorSeeds[^\n]+;/m, `const semiconductorSeeds = ${JSON.stringify(seeds)};`);
const javascript = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText;
const { calendarStockLink, calendarReturnLink, tradingViewSymbol, tradingViewUrl } = await import(`data:text/javascript;base64,${Buffer.from(javascript).toString("base64")}`);

test("calendar links reuse registered semiconductor detail and support every other stock", () => {
  const back = "/new-highs?market=korea&date=2026-10-19&exchange=KOSDAQ";
  const semi = new URL(calendarStockLink(" 080220.kq ", "new-highs", "korea", "2026-10-19", back), "https://example.com");
  assert.equal(semi.pathname, "/semiconductors/080220.KQ");
  assert.equal(semi.searchParams.get("returnTo"), back);
  const other = new URL(calendarStockLink("EURONEXT:MC", "turnover", "europe", "2026-10-19", "/turnover?market=europe"), "https://example.com");
  assert.equal(other.pathname, "/market-stocks/EURONEXT%3AMC");
  assert.equal(other.searchParams.get("source"), "turnover");
  assert.equal(other.searchParams.get("date"), "2026-10-19");
});

test("symbols retain the right exchange and listing code across all six markets", () => {
  for (const [ticker, exchange, expected] of [
    ["035420.KS", "KOSPI", "KRX:035420"], ["080220.KQ", "KOSDAQ", "KRX:080220"],
    ["AAPL", "NASDAQ", "NASDAQ:AAPL"], ["BRK-B", "NYSE", "NYSE:BRK.B"], ["SPY", "AMEX", "AMEX:SPY"],
    ["6503.T", "TSE", "TSE:6503"], ["2330.TW", "TWSE", "TWSE:2330"], ["5347.TWO", "TPEX", "TPEX:5347"],
    ["600519.SS", "SSE", "SSE:600519"], ["000001.SZ", "SZSE", "SZSE:000001"],
    ["EURONEXT:MC", "EURONEXT", "EURONEXT:MC"], ["SAP.DE", "XETRA", "XETR:SAP"],
    ["XETR:SAP", "XETRA", "XETR:SAP"], ["SHEL.L", "LSE", "LSE:SHEL"], ["NESN.SW", "SIX", "SIX:NESN"],
  ]) assert.equal(tradingViewSymbol(ticker, exchange), expected, `${ticker} / ${exchange}`);
  assert.equal(tradingViewSymbol("AAPL", "UNKNOWN"), null);
  assert.equal(tradingViewSymbol("NASDAQ:AAPL", "NYSE"), null);
  assert.equal(tradingViewSymbol("<script>", "NASDAQ"), null);
  assert.equal(tradingViewUrl("NYSE:BRK.B"), "https://www.tradingview.com/symbols/NYSE-BRK.B/");
});

test("return links preserve the original calendar while excluding external and unexpected destinations", () => {
  assert.equal(calendarReturnLink("/sectors?level=sector&period=month"), "/sectors?level=sector&period=month");
  assert.equal(calendarReturnLink("/calendar-history?market=japan&view=year"), "/calendar-history?market=japan&view=year");
  for (const value of [null, "https://evil.example", "//evil.example", "javascript:alert(1)", "/new-highs-elsewhere", "/stocks/A"]) {
    assert.equal(calendarReturnLink(value, "/turnover"), "/turnover");
  }
});
