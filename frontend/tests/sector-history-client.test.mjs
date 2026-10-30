import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";
import { gzipSync } from "node:zlib";
const rankSource = await readFile(new URL("../src/dataClient/sectorRankings.ts", import.meta.url), "utf8");
const rankJs = ts.transpileModule(rankSource, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText;
const rankUrl = `data:text/javascript;base64,${Buffer.from(rankJs).toString("base64")}`;
let source = await readFile(new URL("../src/dataClient/sectorDataClient.ts", import.meta.url), "utf8");
const names = JSON.parse(await readFile(new URL("../../data/seed/korean_company_names.json", import.meta.url), "utf8"));
source = source.replace('import koreanCompanyNames from "../../../data/seed/korean_company_names.json";', `const koreanCompanyNames = ${JSON.stringify(names)};`);
source = source.replace('from "./sectorRankings";', `from "${rankUrl}";`).replace('import { classifiedSectorStock } from "./sectorRankings";', `import { classifiedSectorStock } from "${rankUrl}";`);
source = source.replace('import { requestOriginal } from "./liveStockDataClient";', 'const requestOriginal = async () => { throw new Error("Historical records must not request live prices"); };').replaceAll("import.meta.env.BASE_URL", '"/"');
const js = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText;
const client = await import(`data:text/javascript;base64,${Buffer.from(js).toString("base64")}`);
const stock = (ticker, date, price) => ({ ticker, date, price, sector: "Electronic Technology", industry: "Semiconductors", currency: "KRW", exchange: "KOSPI", turnover: 100, market_cap: 1000, returns: { day: 1, week: 2, month: 3, quarter: 4, year: 5 } });
const snapshot = (date, ticker, price) => ({ schema_version: 1, market: "korea", currency: "KRW", date, fetched_at: date + "T06:30:00Z", stocks: [stock(ticker, date, price)] });
test("archived and latest sector records use verified names without changing prices", async () => {
  const original = globalThis.fetch;
  const current = snapshot("2026-10-20", "024110.KS", 20000), old = snapshot("2026-10-01", "011200.KS", 19000);
  current.stocks[0].name = "중소기업은행";
  old.stocks[0].name = "에이치엠엠";
  globalThis.fetch = async url => new Response(url.includes("daily/") ? gzipSync(JSON.stringify(old)) : JSON.stringify(current));
  try {
    assert.equal((await client.getSectorData()).stocks[0].name, "기업은행");
    const archived = await client.getSectorSnapshot("2026-10-01");
    assert.equal(archived.stocks[0].name, "HMM");
    assert.equal(archived.stocks[0].price, 19000);
  } finally { globalThis.fetch = original; }
});
test("history selection never replaces the latest cache, and detail membership and price use the selected day's snapshot", async () => {
  const original = globalThis.fetch;
  const current = snapshot("2026-10-21", "005930.KS", 140), old = snapshot("2026-10-19", "000001.KS", 100);
  const paths = [];
  globalThis.fetch = async url => {
    const path = new URL(url, "https://example.test").pathname; paths.push(path);
    return new Response(path.includes("daily/") ? gzipSync(JSON.stringify(old)) : JSON.stringify(current));
  };
  try {
    const historical = await client.getSectorSnapshot("2026-10-19", undefined, true);
    assert.equal(historical.archived, true); assert.equal(historical.stocks[0].price, 100); assert.equal(historical.source_fetched_at, undefined);
    assert.equal((await client.getSectorData()).stocks[0].price, 140);
    assert.equal((await client.getSectorStock("000001.KS", new AbortController().signal, "2026-10-19")).price, 100);
    await assert.rejects(() => client.getSectorSnapshot("2026-10-18"), /일치/);
    const before = paths.length;
    await assert.rejects(() => client.getSectorSnapshot("../../index"));
    await assert.rejects(() => client.getSectorSnapshot("2026-02-30"));
    assert.equal(paths.length, before);
  } finally { globalThis.fetch = original; }
});
