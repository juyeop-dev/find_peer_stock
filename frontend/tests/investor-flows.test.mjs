import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import test from "node:test";
import ts from "typescript";
const source=(await readFile(new URL("../src/dataClient/investorDataClient.ts",import.meta.url),"utf8")).replace('import { requestOriginal } from "./liveStockDataClient";','const requestOriginal = (...args) => globalThis.mockInvestorOriginal(...args);');
const js=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText.replaceAll('import.meta.env.BASE_URL','"/"');
const {validateInvestorDay,investorTotals,investorMoney,getInvestorData}=await import(`data:text/javascript;base64,${Buffer.from(js).toString("base64")}`);
const archive=JSON.parse(await readFile(new URL("../../data/investors/index.json",import.meta.url),"utf8"));
test("every archived day pairs both exact-date indices and source flows, including all 244 Korean 2024 trading days",()=>{
  archive.history.forEach(validateInvestorDay);
  assert.equal(archive.history.filter(row=>row.date.startsWith("2024-")).length,244);
  assert.equal(archive.history[0].date,"2024-01-02");
});
test("whole-market totals sum money, never indices or percentages, and invalid pairs fail",()=>{
  const row=archive.history[0],total=investorTotals(row,"all");
  for(const value of total)for(const key of ["buy","sell","net"])assert.equal(value[key],row.markets.reduce((sum,market)=>sum+market.investors.find(other=>other.key===value.key)[key],0));
  const bad=structuredClone(row);bad.markets[0].index.date="2024-01-03";assert.throws(()=>validateInvestorDay(bad));
  assert.throws(()=>investorTotals(row,"unknown"));
  assert.equal(investorMoney(0,true),"0.00");assert.equal(investorMoney(-123e8,true),"-123.00");
});
test("original refresh retains all past records and rejects a response for another requested day",async()=>{
  const originalFetch=globalThis.fetch;
  globalThis.fetch=async()=>Response.json(archive);
  globalThis.mockInvestorOriginal=async()=>({...structuredClone(archive.history[0]),fetched_at:new Date().toISOString(),source_fetched_at:new Date().toISOString()});
  const signal=new AbortController().signal;
  try {
    const before=await getInvestorData(signal),after=await getInvestorData(signal,true,"2024-01-02");
    assert.equal(after.history.length,before.history.length);assert.equal(after.latest_date,before.latest_date);assert.ok(after.source_fetched_at);
    await assert.rejects(()=>getInvestorData(signal,true,"2024-01-03"),/일치/);
  } finally {globalThis.fetch=originalFetch;delete globalThis.mockInvestorOriginal;}
});
