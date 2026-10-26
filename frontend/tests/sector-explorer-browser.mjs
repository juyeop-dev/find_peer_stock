import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { mkdtemp, readFile, rm, mkdir, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve, sep } from "node:path";
import ts from "typescript";

const base=process.env.STOCK_SITE_BASE_URL ?? "http://127.0.0.1:4174";
const source=await (await fetch(base+"/data/sectors/index.json")).json();
const finance=source.stocks.filter(stock=>stock.sector==="Finance"&&stock.date===source.date);
assert.ok(finance.length>50);
const moduleSource=await readFile(new URL("../src/dataClient/sectorRankings.ts",import.meta.url),"utf8");
const js=ts.transpileModule(moduleSource,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const {sortSectorMembers}=await import(`data:text/javascript;base64,${Buffer.from(js).toString("base64")}`);
const executable=process.env.BROWSER_PATH ?? ["C:/Program Files/Google/Chrome/Application/chrome.exe","C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"].find(existsSync);
assert.ok(executable);
const profile=await mkdtemp(join(tmpdir(),"sector-explorer-"));
const browser=spawn(executable,["--headless=new","--disable-gpu","--no-sandbox","--no-first-run","--remote-debugging-port=0",`--user-data-dir=${profile}`,"about:blank"],{windowsHide:true,stdio:"ignore"});
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function until(check,message) { const deadline=Date.now()+90000; while(Date.now()<deadline) {if(await check()) return;await delay(100);}throw new Error(message); }
let socket,send;
try {
  await until(()=>existsSync(join(profile,"DevToolsActivePort")),"Browser unavailable");
  const [port]=(await readFile(join(profile,"DevToolsActivePort"),"utf8")).split(/\r?\n/);
  const targets=await(await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  socket=new WebSocket(targets.find(target=>target.type==="page").webSocketDebuggerUrl);
  await new Promise(resolve=>socket.addEventListener("open",resolve,{once:true}));
  let id=0;const pending=new Map(),exceptions=[],statuses=[],requests=new Map();
  socket.addEventListener("message",event=>{
    const value=JSON.parse(event.data);
    if(value.method==="Runtime.exceptionThrown") exceptions.push(value.params.exceptionDetails);
    if(value.method==="Network.requestWillBeSent"&&value.params.request.postData) {try{requests.set(value.params.requestId,JSON.parse(value.params.request.postData).kind);}catch{}}
    if(value.method==="Network.responseReceived"&&requests.has(value.params.requestId)) statuses.push({kind:requests.get(value.params.requestId),status:value.params.response.status});
    const task=pending.get(value.id);if(!task)return;pending.delete(value.id);clearTimeout(task.timer);value.error?task.reject(new Error(value.error.message)):task.resolve(value.result);
  });
  send=(method,params={})=>new Promise((resolve,reject)=>{const sequence=++id;const timer=setTimeout(()=>{pending.delete(sequence);reject(new Error(method+" timeout"));},15000);pending.set(sequence,{resolve,reject,timer});socket.send(JSON.stringify({id:sequence,method,params}));});
  const evaluate=async expression=>{const result=await send("Runtime.evaluate",{expression,returnByValue:true,awaitPromise:true});if(result.exceptionDetails)throw new Error(JSON.stringify(result.exceptionDetails));return result.result.value;};
  const navigate=route=>send("Page.navigate",{url:base+route});
  const click=selector=>evaluate(`document.querySelector(${JSON.stringify(selector)}).click()`);
  const codes=selector=>evaluate(`[...document.querySelectorAll('${selector} .semiStockLink span')].map(node=>node.innerText)`);
  await send("Runtime.enable");await send("Network.enable");
  await navigate("/semiconductors");
  await until(()=>evaluate("document.querySelectorAll('[aria-label=\"탐색할 섹터\"] option').length>15 && document.querySelectorAll('.semiStockPriceTable tbody tr').length>100"),"Legacy semiconductor classifications missing");
  await evaluate("(()=>{const select=document.querySelector('[aria-label=\"탐색할 섹터\"]');select.value='Finance';select.dispatchEvent(new Event('change',{bubbles:true}));})()");
  await until(()=>evaluate(`document.querySelectorAll('.sectorExplorerMembers tbody tr').length===${finance.length}`),"Finance stocks did not load");
  assert.equal(await evaluate("new URL(location.href).searchParams.get('sector')"),"Finance");
  const expected=finance.map(stock=>stock.code).sort();
  assert.deepEqual((await codes(".sectorExplorerMembers")).sort(),expected);
  for(const [column,key] of [[1,"name"],[3,"exchange"],[4,"price"],[5,"return"],[6,"turnover"],[7,"marketCap"]]) {
    for(let pass=0;pass<2;pass++) {
      await click(`.sectorExplorerMembers thead th:nth-child(${column}) button`);
      const direction=await evaluate(`document.querySelector('.sectorExplorerMembers thead th:nth-child(${column})').getAttribute('aria-sort')`);
      assert.deepEqual(await codes(".sectorExplorerMembers"),sortSectorMembers(finance,key,direction==="ascending"?"asc":"desc","month").map(stock=>stock.code));
    }
  }
  const largest=[...finance].sort((a,b)=>b.market_cap-a.market_cap)[0];
  await evaluate(`[...document.querySelectorAll('.sectorExplorerMembers .semiStockLink')].find(link=>link.querySelector('span').innerText===${JSON.stringify(largest.code)}).click()`);
  await until(()=>evaluate("Boolean(document.querySelector('.stockMetricTable tbody td'))"),"Finance detail metrics missing");
  const metricAlignments=await evaluate("({heads:[...document.querySelectorAll('.stockMetricTable th')].map(node=>getComputedStyle(node).textAlign),values:[...document.querySelectorAll('.stockMetricTable td')].map(node=>getComputedStyle(node).textAlign),text:[...document.querySelectorAll('.stockMetricTable td')].map(node=>node.innerText)})");
  assert.deepEqual(metricAlignments.heads,Array(6).fill("right"));assert.deepEqual(metricAlignments.values,Array(6).fill("right"));
  assert.ok(metricAlignments.text.slice(0,2).every(value=>value==="—"||value.endsWith("배")));
  for(const width of [1440,320]) {
    await send("Emulation.setDeviceMetricsOverride",{width,height:1000,deviceScaleFactor:1,mobile:false});
    assert.equal(await evaluate("document.documentElement.scrollWidth>innerWidth"),false,`Metrics overflow ${width}`);
    await evaluate("document.querySelector('.stockMetricTable').scrollIntoView({block:'center'})");
    const screenshot=await send("Page.captureScreenshot",{format:"png"});
    const folder=new URL("../../data/tmp_2024/ui/",import.meta.url);await mkdir(folder,{recursive:true});await writeFile(new URL(`metrics-${width}.png`,folder),Buffer.from(screenshot.data,"base64"));
  }
  await click(".semiBreadcrumb a");
  await until(()=>evaluate("document.querySelector('[aria-label=\"탐색할 섹터\"]')?.value==='Finance' && Boolean(document.querySelector('.sectorExplorerMembers'))"),"Sector detail return lost selection");
  await send("Emulation.setDeviceMetricsOverride",{width:1440,height:1000,deviceScaleFactor:1,mobile:false});
  await navigate(`/sector-trends?${new URLSearchParams({sector:"Finance",group:"Finance\tMajor Banks"})}`);
  await until(()=>evaluate("Boolean(document.querySelector('.sectorExplorerChart .semiChart .semiLine'))"),"Non-semiconductor daily trend missing");
  assert.ok(await evaluate("document.querySelector('.sectorExplorerChart h2').innerText.includes('은행')"));
  await evaluate("[...document.querySelectorAll('.sectorExplorerChart .semiPeriodTabs button')].find(button=>button.innerText==='1년').click()");
  await until(()=>evaluate("document.querySelector('.sectorExplorerChart .semiPeriodTabs .active')?.innerText==='1년' && Boolean(document.querySelector('.sectorExplorerChart .semiLine'))"),"Year trend unavailable");
  const before=statuses.length;
  await click(".refreshButton");
  await until(()=>Promise.resolve(statuses.slice(before).some(value=>value.kind==="sectors"&&value.status===200)&&statuses.slice(before).some(value=>value.kind==="history"&&value.status===200)),"Source refresh did not query both current sector and history");
  await until(()=>evaluate("!document.querySelector('.refreshButton').disabled && Boolean(document.querySelector('.sectorExplorerChart .semiLine'))"),"Refreshed trend did not finish");
  for(const width of [1440,320]) {
    await send("Emulation.setDeviceMetricsOverride",{width,height:1000,deviceScaleFactor:1,mobile:false});
    assert.equal(await evaluate("document.documentElement.scrollWidth>innerWidth"),false,`Explorer overflow ${width}`);
  }
  await navigate("/semiconductors/trends");
  await until(()=>evaluate("Boolean(document.querySelector('.semiTrendTable')) && document.querySelector('[aria-label=\"탐색할 섹터\"]')?.value==='semiconductors'"),"Original semiconductor trends unavailable");
  await navigate("/sectors?level=sector&selected=Finance");
  await until(()=>evaluate(`document.querySelectorAll('.sectorMemberTable tbody tr').length===${finance.length}`),"Sector ranking members unavailable");
  for(const [index,key] of [[1,"name"],[2,"exchange"],[3,"price"],[4,"return"],[5,"turnover"],[6,"marketCap"],[7,"basis"]]) {
    for(let pass=0;pass<2;pass++) {
      await click(`.sectorMemberTable thead th:nth-child(${index}) button`);
      const direction=await evaluate(`document.querySelector('.sectorMemberTable thead th:nth-child(${index})').getAttribute('aria-sort')`);
      assert.deepEqual(await codes(".sectorMemberTable"),sortSectorMembers(finance,key,direction==="ascending"?"asc":"desc","day").map(stock=>stock.code));
    }
  }
  assert.deepEqual(exceptions,[]);
  console.log(JSON.stringify({result:"PASS",financeStocks:finance.length,checks:"Other sector stocks and real daily trends, legacy semiconductor views, 26 column sort toggles, detail/return, metric header and number alignment, source refresh, 1440/320px"}));
} finally {
  if(send&&socket?.readyState===WebSocket.OPEN)await send("Browser.close").catch(()=>{});
  socket?.close();browser.kill();
  assert.ok(resolve(profile).startsWith(resolve(tmpdir())+sep));await rm(profile,{recursive:true,force:true,maxRetries:10,retryDelay:100});
}
