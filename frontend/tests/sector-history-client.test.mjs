import assert from "node:assert/strict";
import { readFile, mkdtemp, mkdir, writeFile, rm } from "node:fs/promises";
import {join} from "node:path";
import {tmpdir} from "node:os";
import test from "node:test";
import ts from "typescript";
import {compactSector, compactPublicData, compactJsonWhitespace} from "../build/compact-public-data.mjs";
import { gzipSync, gunzipSync } from "node:zlib";
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


test("columnar sector archives retain precision, nulls, absent properties and original row order",()=>{
  const original={schema_version:1,date:"2015-01-02",stocks:[{ticker:"A",price:1.1234567890123,zero:0,returns:{week:null,day:-7}},{ticker:"B",optional:null,price:0.5}]};
  const packed=compactSector(original);
  assert.deepEqual(client.expandSectorArchive(packed),original);
  for(const bad of [
    {...packed,encoding:"unknown"},
    {...packed,stock_fields:[["ticker","ticker"]]},
    {...packed,stock_fields:[["__proto__"]]},
    {...packed,stock_rows:[[99,1]]},
    {...packed,stock_rows:[[0]]},
    {...packed,stock_rows:[[0.5,1]]},
  ])assert.throws(()=>client.expandSectorArchive(bad));
});

test("latest sector reads gzip, host-decoded JSON and legacy fallback without dropping cached prices",async()=>{
  const original=globalThis.fetch;
  try {
    for(const [date,price,compressed] of [["2026-10-22",160,true],["2026-10-23",170,false]]) {
      const value=snapshot(date,"005930.KS",price);
      globalThis.fetch=async()=>new Response(compressed?gzipSync(JSON.stringify(value)):JSON.stringify(value));
      assert.equal((await client.getSectorData()).stocks[0].price,price);
    }
    const paths=[],legacy=snapshot("2026-10-24","005930.KS",180);
    globalThis.fetch=async url=>{
      const path=new URL(url,"https://example.test").pathname;paths.push(path);
      return path.endsWith('.gz')?new Response('',{status:404}):Response.json(legacy);
    };
    assert.equal((await client.getSectorData()).stocks[0].price,180);
    assert.deepEqual(paths,["/data/sectors/index.json.gz","/data/sectors/index.json"]);
    globalThis.fetch=async()=>{throw new Error('Source unavailable');};
    assert.equal((await client.getSectorData()).stocks[0].price,180);
  } finally {globalThis.fetch=original;}
});

test("latest sector artifact gzip preserves original byte precision and leaves source data separate",async()=>{
  const directory=await mkdtemp(join(tmpdir(),"sector-public-gzip-"));
  try {
    const target=join(directory,"data/sectors");await mkdir(target,{recursive:true});
    const bytes=Buffer.from('{"amount":9007199254740993,"price":1.1234567890123456789,"name":"한국","missing":null}\n');
    await writeFile(join(target,"index.json"),bytes);
    await compactPublicData(directory);
    assert.deepEqual(gunzipSync(await readFile(join(target,"index.json.gz"))),bytes);
    await assert.rejects(()=>readFile(join(target,"index.json")),{code:"ENOENT"});
  } finally {await rm(directory,{recursive:true,force:true});}
});

test("report whitespace compaction keeps exact numerical tokens, escaped quotes and spaces inside strings",()=>{
  const raw=Buffer.from(String.raw`{
    "amount": 9007199254740993,
    "price": 1.1234567890123456789,
    "exponent": 1.000e+20,
    "label": "한국 주식 \"quoted\" \\ path",
    "rows": [null, -0.0, true, {"name": "  two spaces  "}]
  }`);
  const output=compactJsonWhitespace(raw);
  assert.deepEqual(JSON.parse(output),JSON.parse(raw));
  for(const token of ['9007199254740993','1.1234567890123456789','1.000e+20','-0.0','  two spaces  '])assert.ok(output.toString().includes(token));
  assert.ok(output.length<raw.length);
});
