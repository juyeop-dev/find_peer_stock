import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const transpile = text => ts.transpileModule(text,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const historySource = (await readFile(new URL("../src/dataClient/stockHistoryClient.ts",import.meta.url),"utf8")).replace('import { liveDetailFor, requestOriginal } from "./liveStockDataClient";', 'const liveDetailFor=()=>undefined; const requestOriginal=()=>{throw new Error("No original request expected")};');
const historyUrl = `data:text/javascript;base64,${Buffer.from(transpile(historySource)).toString("base64")}`;
const source = (await readFile(new URL("../src/dataClient/sectorExplorer.ts",import.meta.url),"utf8")).replace('from "./stockHistoryClient"',`from "${historyUrl}"`);
const {sectorHistorySeries,sectorHistoryForDate} = await import(`data:text/javascript;base64,${Buffer.from(transpile(source)).toString("base64")}`);
const history = (ticker, points, currency="KRW") => ({ticker,currency,history:points.map(([date,value])=>({date,close:value,adjusted_close:value,volume:null}))});
test("sector charts use a complete preserved curve for the selected day without mixing adjustment bases", () => {
  const current=history("A",[["2019-12-20",50],["2026-10-28",80]]);
  const prior={ticker:"A",currency:"KRW",source:"Verified original",complete_history:true,prices:[["2025-10-20",100,100],["2026-10-28",120,120],["2026-10-29",130,130]]};
  current.prior_snapshots=[{...prior,complete_history:false}];
  assert.equal(sectorHistoryForDate(current,"2026-10-29"),current,"A partial difference snapshot cannot become a chart curve");
  current.prior_snapshots=[{...prior,currency:"USD"}];
  assert.equal(sectorHistoryForDate(current,"2026-10-29"),current);
  current.prior_snapshots=[prior];
  const selected=sectorHistoryForDate(current,"2026-10-29");
  assert.equal(selected.history[0].adjusted_close,100);
  assert.equal(selected.history.at(-1).date,"2026-10-29");
  assert.equal(sectorHistorySeries([selected],"year","2026-10-29").points.at(-1).value,130);
});
test("a fixed cohort uses adjusted closes and excludes recent listings, stale and foreign-currency histories", () => {
  const a=history("A",[["2026-09-25",100],["2026-10-23",110],["2026-10-26",120]]);
  a.history[2].close=240; // A split must not double the total return.
  const b=history("B",[["2026-09-25",200],["2026-10-26",180]]);
  const recent=history("IPO",[["2026-10-23",1],["2026-10-26",20]]);
  const stale=history("STALE",[["2026-09-25",1],["2026-10-23",10]]);
  const foreign=history("USD",[["2026-09-25",1],["2026-10-26",10]],"USD");
  const result=sectorHistorySeries([a,b,recent,stale,foreign],"month","2026-10-26");
  assert.equal(result.count,2);assert.equal(result.start,"2026-09-26");
  assert.ok(Math.abs(result.points.at(-1).value-105)<1e-10);
  assert.equal(result.points.find(point=>point.date==="2026-10-23").value,105);
});
test("missing baselines never create a synthetic index, and leap-year periods use calendar years", () => {
  assert.deepEqual(sectorHistorySeries([],"year","2024-02-29").points,[]);
  assert.equal(sectorHistorySeries([],"year","2024-02-29").start,"2023-02-28");
  assert.equal(sectorHistorySeries([],"day","2026-10-26").start,"2026-10-25");
});
