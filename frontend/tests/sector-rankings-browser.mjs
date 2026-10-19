import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../../", import.meta.url));
const base = process.env.STOCK_SITE_BASE_URL ?? "http://127.0.0.1:4173";
const browserPath = process.env.BROWSER_PATH ?? ["C:/Program Files/Google/Chrome/Application/chrome.exe", "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", "/usr/bin/chromium", "/usr/bin/google-chrome"].find(existsSync);
assert.ok(browserPath, "Set BROWSER_PATH to Chromium.");
const profile = await mkdtemp(join(tmpdir(), "stock-information-production-"));
const browser = spawn(browserPath, ["--headless=new", "--disable-gpu", "--no-sandbox", "--no-first-run", "--no-default-browser-check", "--remote-debugging-port=0", `--user-data-dir=${profile}`, "about:blank"], {windowsHide:true,stdio:"ignore"});
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
async function until(predicate, message) {
  const end = Date.now() + 60000;
  while (Date.now() < end) {if (await predicate()) return; await delay(100);}
  throw new Error(message);
}
let socket, send;
try {
  await until(() => existsSync(join(profile, "DevToolsActivePort")), "Chrome debugger did not start");
  const [port] = (await readFile(join(profile, "DevToolsActivePort"), "utf8")).split(/\r?\n/);
  const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  socket = new WebSocket(targets.find(target => target.type === "page").webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {socket.addEventListener("open", resolve, {once:true});socket.addEventListener("error",reject,{once:true});});
  let sequence = 0;
  const pending = new Map(), exceptions = [], requests = new Map(), statuses = [];
  socket.addEventListener("message", event => {
    const message = JSON.parse(event.data);
    if (message.method === "Runtime.exceptionThrown") exceptions.push(message.params.exceptionDetails);
    if (message.method === "Network.requestWillBeSent" && message.params.request.postData) {
      try {const body = JSON.parse(message.params.request.postData);if (["information","history","sectors"].includes(body.kind)) requests.set(message.params.requestId,body.kind);} catch {}
    }
    if (message.method === "Network.responseReceived" && requests.has(message.params.requestId)) statuses.push({kind:requests.get(message.params.requestId),status:message.params.response.status});
    const task = pending.get(message.id);
    if (!task) return;
    pending.delete(message.id);clearTimeout(task.timer);
    message.error ? task.reject(new Error(message.error.message)) : task.resolve(message.result);
  });
  send = (method, params = {}) => new Promise((resolve, reject) => {
    const id = ++sequence;
    const timer = setTimeout(() => {pending.delete(id);reject(new Error(`${method} timeout`));},10000);
    pending.set(id,{resolve,reject,timer});socket.send(JSON.stringify({id,method,params}));
  });
  const evaluate = async expression => {
    const result = await send("Runtime.evaluate",{expression,returnByValue:true,awaitPromise:true});
    if (result.exceptionDetails) throw new Error(result.exceptionDetails.text);
    return result.result.value;
  };
  await send("Runtime.enable");await send("Network.enable");

  const waitRows = () => until(() => evaluate("document.querySelectorAll('.sectorRankingTable tbody tr').length>50"), "Sector rows did not load");
  await send("Page.navigate",{url:base+"/sectors"});
  await waitRows();
  assert.equal(await evaluate("document.querySelector('.sectorRankingTable [aria-sort=descending]').innerText.includes('거래대금')"),true);
  const rowCount = await evaluate("document.querySelectorAll('.sectorRankingTable tbody tr').length");
  const click = expression => evaluate(`(${expression}).click()`);
  await click("document.querySelector('.sectorRankingTable th:nth-child(3) button')");
  const returns = await evaluate("[...document.querySelectorAll('.sectorRankingTable tbody tr')].map(row=>parseFloat(row.children[2].innerText)).filter(Number.isFinite)");
  assert.ok(returns.every((value,i)=>i===0||returns[i-1]>=value),"Sector gain sorting failed");
  await click("[...document.querySelectorAll('[aria-label=\"수익률 기간\"] button')].find(button=>button.innerText==='1개월')");
  await until(()=>evaluate("document.querySelector('.sectorTableCaption').innerText.includes('1개월')"),"Period did not change");
  await evaluate("(()=>{const input=document.querySelector('.sectorSearch input');Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,'반도체');input.dispatchEvent(new Event('input',{bubbles:true}));})()");
  await until(()=>evaluate(`document.querySelectorAll('.sectorRankingTable tbody tr').length>0 && document.querySelectorAll('.sectorRankingTable tbody tr').length<${rowCount}`),"Sector search failed");
  await evaluate("(()=>{const select=document.querySelectorAll('.sectorFilters select')[1];select.value='KOSDAQ';select.dispatchEvent(new Event('change',{bubbles:true}));})()");
  await until(()=>evaluate("document.querySelectorAll('.sectorMemberTable tbody tr').length>0 && [...document.querySelectorAll('.sectorMemberTable tbody tr')].every(row=>row.children[1].innerText==='KOSDAQ')"),"Board filter failed");
  await evaluate("(()=>{const select=document.querySelectorAll('.sectorFilters select')[1];select.value='';select.dispatchEvent(new Event('change',{bubbles:true}));})()");
  await until(()=>evaluate("[...document.querySelectorAll('.sectorMemberTable tbody tr')].some(row=>row.children[1].innerText==='KOSPI')"),"Board reset failed");
  await click("[...document.querySelectorAll('.sectorNameButton')].find(button=>button.innerText.trim().endsWith('반도체'))");
  await until(()=>evaluate("document.querySelector('.sectorRankingTable tr.selected .sectorNameButton')?.innerText.trim().endsWith('반도체')"),"Sector selection did not update");
  const detailName=await evaluate("document.querySelector('.sectorRankingTable tr.selected .sectorRepresentative').innerText");
  await click("document.querySelector('.sectorRankingTable tr.selected .sectorRepresentative')");
  await until(()=>evaluate("Boolean(document.querySelector('.marketStockPage h1')) && Boolean(document.querySelector('.stockHistoryChart .semiChart')) && Boolean(document.querySelector('.stockInformationPanel table'))"),"Sector stock detail did not load");
  assert.equal(await evaluate("new URL(location.href).searchParams.get('source')"),"sectors");
  await click("document.querySelector('.semiBreadcrumb a')");
  await until(()=>evaluate("Boolean(document.querySelector('.sectorRankingTable')) && document.querySelector('.sectorSearch input')?.value==='반도체'"),"Sector return failed");
  assert.equal(await evaluate("new URL(location.href).searchParams.get('period')"),"month");
  await evaluate("(()=>{const input=document.querySelector('.sectorSearch input');Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,'');input.dispatchEvent(new Event('input',{bubbles:true}));})()");
  await waitRows();
  // A whole-market source query must succeed, and a later failure must retain the table.
  const before=statuses.length;
  await click("document.querySelector('.refreshButton')");
  await until(()=>Promise.resolve(statuses.slice(before).some(item=>item.kind==='sectors'&&item.status===200)),"Original sector refresh did not return HTTP 200");
  await until(()=>evaluate("!document.querySelector('.refreshButton').disabled"),"Sector refresh did not complete");
  for (const width of [1440,900,320]) {
    await send("Emulation.setDeviceMetricsOverride",{width,height:1100,deviceScaleFactor:1,mobile:false});
    assert.equal(await evaluate("document.documentElement.scrollWidth>innerWidth"),false,`Sector page overflows at ${width}px`);
    if (width!==900) {
      await mkdir(join(root,'data/tmp_info_update'),{recursive:true});
      const screenshot=await send('Page.captureScreenshot',{format:'png'});
      await writeFile(join(root,`data/tmp_info_update/sector-${width}.png`),Buffer.from(screenshot.data,'base64'));
    }
  }
  const retained=await evaluate("document.querySelector('.sectorRankingTable tbody').innerText");
  socket.addEventListener('message',event=>{
    const item=JSON.parse(event.data);
    if(item.method==='Fetch.requestPaused') {
      const preflight=item.params.request.method==='OPTIONS';
      void send('Fetch.fulfillRequest',{requestId:item.params.requestId,responseCode:preflight?204:502,responseHeaders:[{name:'Content-Type',value:'application/json'},{name:'Access-Control-Allow-Origin',value:new URL(base).origin},{name:'Access-Control-Allow-Methods',value:'POST, OPTIONS'},{name:'Access-Control-Allow-Headers',value:'Content-Type'}],body:preflight?'':Buffer.from(JSON.stringify({error:'의도한 원본 조회 실패'})).toString('base64')});
    }
  });
  await send('Fetch.enable',{patterns:[{urlPattern:'*workers.dev/refresh',requestStage:'Request'}]});
  await click("document.querySelector('.refreshButton')");
  await until(()=>evaluate("document.querySelector('.errorNotice')?.innerText.includes('의도한 원본 조회 실패')"),'Failure did not appear');
  assert.equal(await evaluate("document.querySelector('.sectorRankingTable tbody').innerText"),retained);
  assert.deepEqual(exceptions,[]);
  console.log(JSON.stringify({result:'PASS',rowCount,detailName,checks:'sector ranking, period, sort, search, board, stock detail and return, native refresh, failure retention, 1440/900/320 widths'}));
} finally {
  if (send && socket?.readyState === WebSocket.OPEN) await send("Browser.close").catch(()=>{});
  socket?.close();browser.kill();
  assert.ok(resolve(profile).startsWith(resolve(tmpdir())+sep));
  await rm(profile,{recursive:true,force:true,maxRetries:10,retryDelay:100});
}
