import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import {gzipSync} from "node:zlib";
import ts from "typescript";

let source = await readFile(new URL("../src/dataClient/stockInformationClient.ts", import.meta.url), "utf8");
const profiles = JSON.parse(await readFile(new URL("../../data/seed/company_profiles.json", import.meta.url), "utf8"));
source = source.replace('import companyProfiles from "../../../data/seed/company_profiles.json";', `const companyProfiles = ${JSON.stringify(profiles)};`);
source = source.replace('import { requestOriginal, rememberInformationQuote } from "./liveStockDataClient";', 'const requestOriginal = () => { throw new Error("unexpected network"); }; const rememberInformationQuote = () => {};');
source = source.replaceAll('import.meta.env.BASE_URL','"/"');
const javascript = ts.transpileModule(source, {compilerOptions: {module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022}}).outputText;
const {mergeInformation,decodePublishedInformation,getStockInformation} = await import(`data:text/javascript;base64,${Buffer.from(javascript).toString("base64")}`);
const statement = (period_end, currency, revenue) => ({type:"quarterly",period_end,currency,revenue,source:"fixture"});

test("compressed and host-decoded financial archives retain Unicode, zero, losses and original precision", async () => {
  const value={ticker:"LEGACY",fetched_at:"2026-10-30T00:00:00Z",quote:null,metrics:{per:0},financials:[statement("2019-03-31","TWD",-123.123456789)],warnings:["확인된 원본만 표시"]};
  const body=JSON.stringify(value);
  assert.deepEqual(await decodePublishedInformation(new Response(gzipSync(body))),value);
  assert.deepEqual(await decodePublishedInformation(new Response(body)),value);
  const original=globalThis.fetch,requests=[];
  globalThis.fetch=async url=>{requests.push(url);return String(url).includes('.json.gz')?new Response('',{status:404}):Response.json(value);};
  try {
    assert.deepEqual(JSON.parse(JSON.stringify(await getStockInformation("LEGACY"))),value);
    assert.equal(requests.length,2);
    assert.ok(requests[0].includes('.json.gz')&&requests[1].includes('.json?'));
  } finally {globalThis.fetch=original;}
  await assert.rejects(decodePublishedInformation(new Response(Buffer.from([0x1f,0x8b,1,2]))));
});

test("an unavailable older provider period cannot reset coverage of retained reported financials to zero", () => {
  const coverage={start:"2021-01-01",end:"2021-12-31",periods:1,annual_periods:1,quarterly_periods:0,note:"reported only"};
  const older={...statement("2021-12-31","USD",100),type:"annual"};
  const previous={metrics:{},financials:[older],historical_2021_coverage:coverage};
  const fresh={metrics:{},financials:[statement("2025-03-31","USD",200)],historical_2021_coverage:{...coverage,periods:0,annual_periods:0}};
  const result=mergeInformation(previous,fresh);
  assert.deepEqual(result.financials[0],older);
  assert.equal(result.historical_2021_coverage.periods,1);
  assert.equal(result.historical_2021_coverage.annual_periods,1);
});
test("refresh preserves older reported periods while replacing a revised period and its reporting currency", () => {
  const old = {metrics:{eps:20},metrics_currency:"TWD",financials:[statement("2025-03-31","TWD",100),statement("2025-06-30","TWD",200)]};
  const result = mergeInformation(old,{metrics:{eps:null},metrics_currency:"USD",financials:[statement("2025-06-30","USD",7),statement("2025-09-30","USD",8)]});
  assert.equal(result.financials.length,3);
  assert.equal(result.financials[0].currency,"TWD");
  assert.equal(result.financials[1].currency,"USD");
  assert.equal(result.financials[1].revenue,7);
  assert.equal(result.metrics.eps,undefined,"A TWD EPS must not survive under a USD currency label");
});
test("UTC original quotes supersede older KST snapshots across midnight", async () => {
  const source = (await readFile(new URL("../src/dataClient/liveStockDataClient.ts", import.meta.url), "utf8")).replace("import.meta.env.VITE_LIVE_API_URL", "undefined");
  const javascript = ts.transpileModule(source, {compilerOptions: {module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
  const {rememberInformationQuote,applyQuote,applyIndex} = await import(`data:text/javascript;base64,${Buffer.from(javascript).toString("base64")}`);
  rememberInformationQuote({ticker:"TEST",price:2,market_cap:20,currency:"USD",fetched_at:"2026-10-19T15:01:00Z"});
  const before = {ticker:"TEST",price:1,fetched_at:"2026-10-20T00:00:00+09:00"};
  assert.equal(applyQuote(before).price,2);
  assert.equal(applyIndex({generated_at:before.fetched_at,stocks:[{ticker:"TEST",market_cap:10}]}).stocks[0].market_cap,20);
  rememberInformationQuote({ticker:"TEST",price:0.5,fetched_at:"2026-10-19T14:59:00Z"});
  assert.equal(applyQuote(before).price,2);
  rememberInformationQuote({ticker:"TEST",price:0.25,status:"stale",provider_time:"2026-09-01T00:00:00Z",fetched_at:"2026-10-19T16:00:00Z"});
  assert.equal(applyQuote(before).price,2,"An old source bar must not overwrite a newer price just because it was queried later");
});
