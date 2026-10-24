import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve, sep } from "node:path";
import ts from "typescript";

const base=process.env.STOCK_SITE_BASE_URL ?? "http://127.0.0.1:4173";
const day="2024-07-01";
const get=async path=>{const response=await fetch(base+path+"?t="+Date.now());assert.equal(response.status,200);return response.json();};
const snapshot=await get(`/data/sectors/daily/${day}.json`);
const report=await get(`/data/turnover/korea/2024_07/${day}.json`);
const index=await get("/data/turnover/index.json");
const history=await get("/data/turnover/history/korea/2024.json");
const totals=history.months.flatMap(month=>month.stocks).reduce((sum,stock)=>sum+(stock.turnover_by_currency.KRW ?? 0),0);
assert.equal(totals,index.reports.filter(report=>report.market==="korea"&&report.date.startsWith("2024")).reduce((sum,report)=>sum+report.total_turnover,0));
const source=await readFile(new URL("../src/dataClient/sectorRankings.ts",import.meta.url),"utf8");
const javascript=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const {sectorRankings}=await import(`data:text/javascript;base64,${Buffer.from(javascript).toString("base64")}`);
const key="Energy Minerals\tRefining & Holdings";
const browserPath=process.env.BROWSER_PATH ?? ["C:/Program Files/Google/Chrome/Application/chrome.exe","C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe","/usr/bin/chromium","/usr/bin/google-chrome"].find(existsSync);
assert.ok(browserPath);
const profile=await mkdtemp(join(tmpdir(),"korea-recalculated-history-"));
const browser=spawn(browserPath,["--headless=new","--disable-gpu","--no-sandbox","--no-first-run","--no-default-browser-check","--remote-debugging-port=0",`--user-data-dir=${profile}`,"about:blank"],{windowsHide:true,stdio:"ignore"});
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function until(predicate,message){const end=Date.now()+45000;while(Date.now()<end){if(await predicate())return;await delay(100);}throw new Error(message);}
let socket,send;
try {
  await until(()=>existsSync(join(profile,"DevToolsActivePort")),"Browser did not start");
  const [port]=(await readFile(join(profile,"DevToolsActivePort"),"utf8")).split(/\r?\n/);
  const targets=await(await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  socket=new WebSocket(targets.find(target=>target.type==="page").webSocketDebuggerUrl);
  await new Promise((resolve,reject)=>{socket.addEventListener("open",resolve,{once:true});socket.addEventListener("error",reject,{once:true});});
  let sequence=0;
  const pending=new Map(),exceptions=[],sourceRequests=[];
  socket.addEventListener("message",event=>{
    const item=JSON.parse(event.data);
    if(item.method==="Runtime.exceptionThrown")exceptions.push(item.params.exceptionDetails);
    if(item.method==="Network.requestWillBeSent"&&item.params.request.url.includes("workers.dev/refresh"))sourceRequests.push(item.params.request.url);
    const task=pending.get(item.id);if(task){pending.delete(item.id);clearTimeout(task.timer);item.error?task.reject(new Error(item.error.message)):task.resolve(item.result);}
  });
  send=(method,params={})=>new Promise((resolve,reject)=>{const id=++sequence;const timer=setTimeout(()=>reject(new Error(method+" timeout")),10000);pending.set(id,{resolve,reject,timer});socket.send(JSON.stringify({id,method,params}));});
  const evaluate=async expression=>{const result=await send("Runtime.evaluate",{expression,returnByValue:true,awaitPromise:true});if(result.exceptionDetails)throw new Error(result.exceptionDetails.text);return result.result.value;};
  await send("Runtime.enable");await send("Network.enable");
  await send("Page.navigate",{url:`${base}/sectors?date=${day}&selected=${encodeURIComponent(key)}`});
  await until(()=>evaluate("document.querySelectorAll('.sectorMemberTable tbody tr').length===4"),"Historical refinery did not open");
  assert.ok(await evaluate("document.body.innerText.includes('KRX 일별 확정 시가총액')"));
  assert.equal(await evaluate("document.body.innerText.includes('당시 시가총액이 없어')"),false);
  for(const [period,label] of [["day","오늘"],["week","1주"],["month","1개월"],["quarter","3개월"],["year","1년"]]) {
    await evaluate(`[...document.querySelectorAll('[aria-label="수익률 기간"] button')].find(button=>button.innerText===${JSON.stringify(label)}).click()`);
    await until(()=>evaluate(`document.querySelector('.sectorTableCaption').innerText.includes(${JSON.stringify(label)})`),"Period did not change");
    const text=await evaluate("document.querySelector('.sectorSelectedReturn').innerText");
    const expected=sectorRankings(snapshot,"industry",period).find(row=>row.key===key).value;
    if(expected===null)assert.ok(["—","-"].includes(text),"Unavailable lookback must remain visibly unavailable");
    else assert.ok(Math.abs(parseFloat(text)-expected)<.0051,`Historical ${period}: ${text} != ${expected}`);
  }
  const beforeSource=sourceRequests.length;
  await send("Page.navigate",{url:`${base}/turnover?market=korea&date=${day}`});
  await until(()=>evaluate("document.querySelectorAll('.turnoverTable tbody tr').length===30"),"Historical daily turnover did not load");
  assert.ok(await evaluate("document.querySelector('.dataRefreshStatus').innerText.includes('KRX 일별 확정')"));
  assert.ok(await evaluate("document.querySelector('.turnoverScope').innerText.includes('일별 확정 기준')"));
  const prices=await evaluate("[...document.querySelectorAll('.turnoverTable tbody tr')].map(row=>Number(row.children[2].childNodes[0].textContent.replace(/[^0-9]/g,'')))");
  assert.deepEqual(prices,report.entries.map(entry=>entry.price));
  const saved=await evaluate("document.querySelector('.turnoverTable tbody').innerText");
  await evaluate("document.querySelector('.refreshButton').click()");await delay(300);
  await until(()=>evaluate("!document.querySelector('.refreshButton').disabled"),"Historical reload did not finish");
  assert.equal(await evaluate("document.querySelector('.turnoverTable tbody').innerText"),saved);
  assert.equal(sourceRequests.length,beforeSource);
  for(const width of [1440,390]){await send("Emulation.setDeviceMetricsOverride",{width,height:1100,deviceScaleFactor:1,mobile:false});assert.equal(await evaluate("document.documentElement.scrollWidth>innerWidth"),false);}
  assert.deepEqual(exceptions,[]);
  console.log(JSON.stringify({result:"PASS",date:day,sectorPeriods:5,turnoverRows:30,checks:"dated caps, corrected refinery members, restored turnover labels, saved prices and ranks, no intraday overwrite, annual totals, desktop/mobile"}));
} finally {
  if(send&&socket?.readyState===WebSocket.OPEN)await send("Browser.close").catch(()=>{});
  socket?.close();browser.kill();assert.ok(resolve(profile).startsWith(resolve(tmpdir())+sep));
  await rm(profile,{recursive:true,force:true,maxRetries:10,retryDelay:100});
}
