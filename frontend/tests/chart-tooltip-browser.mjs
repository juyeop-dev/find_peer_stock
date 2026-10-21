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


  const measurements=[];
  for (const route of ['/semiconductors/000660.KS','/stocks/2330.TW','/semiconductors/trends','/credit-balance']) {
    await send('Page.navigate',{url:base+route});
    await until(()=>evaluate("Boolean(document.querySelector('.semiChart .semiLine'))"),route+' chart did not load');
    for (const width of [1440,900,390]) {
      await send('Emulation.setDeviceMetricsOverride',{width,height:1000,deviceScaleFactor:1,mobile:false});
      for (const fraction of [.1,.5,.9]) {
        const target=await evaluate(`(()=>{
          const svg=document.querySelector('.semiChart svg');svg.scrollIntoView({block:'center'});
          const points=[...svg.querySelector('.semiLine').getAttribute('d').matchAll(/[ML]([\\d.-]+),([\\d.-]+)/g)];
          const point=points[Math.round((points.length-1)*${fraction})];
          const position=new DOMPoint(Number(point[1]),Number(point[2]));
          const chart=svg.parentElement;chart.scrollLeft=0;
          const before=position.matrixTransform(svg.getScreenCTM());
          chart.scrollLeft=Math.max(0,before.x-chart.getBoundingClientRect().left-chart.clientWidth/2);
          const screen=position.matrixTransform(svg.getScreenCTM());return {x:screen.x,y:screen.y};
        })()`);
        await send('Input.dispatchMouseEvent',{type:'mouseMoved',x:target.x,y:target.y});
        await until(()=>evaluate(`(()=>{const dot=document.querySelector('.semiDot').getBoundingClientRect();return Math.abs(dot.left+dot.width/2-${target.x})<2 && Math.abs(dot.top+dot.height/2-${target.y})<2;})()`),route+' pointer did not align');
        const info=await evaluate("(()=>{const dot=document.querySelector('.semiDot').getBoundingClientRect(),tip=document.querySelector('.semiChartReadout'),rect=tip.getBoundingClientRect(),chart=document.querySelector('.semiChart'),bounds=chart.getBoundingClientRect();return {date:tip.querySelector('strong').innerText,text:tip.innerText,gap:rect.top-(dot.top+dot.height/2),left:rect.left,right:rect.right,chartLeft:bounds.left,chartRight:bounds.left+chart.clientWidth,visible:getComputedStyle(tip).visibility,bottom:rect.bottom,chartBottom:bounds.bottom};})()");
        assert.equal(info.visible,'visible',JSON.stringify({route,width,fraction,...info}));
        assert.ok(Math.abs(info.gap-12)<2,'Tooltip must follow below its dot: '+JSON.stringify({route,width,fraction,...info}));
        assert.ok(info.left>=info.chartLeft-1&&info.right<=info.chartRight+1,'Tooltip must fit the visible scrolled chart: '+JSON.stringify(info));
        assert.ok(info.bottom<=info.chartBottom+1,'Tooltip must not be clipped below the chart');
        measurements.push({route,width,fraction,date:info.date,gap:info.gap});
      }
    }
  }
  assert.deepEqual(exceptions,[]);
  console.log(JSON.stringify({result:'PASS',checks:measurements.length,routes:4,widths:[1440,900,390],gap:'12px below active point, clamped to visible scrolled chart'}));
} finally {
  if (send && socket?.readyState === WebSocket.OPEN) await send("Browser.close").catch(()=>{});
  socket?.close();browser.kill();
  assert.ok(resolve(profile).startsWith(resolve(tmpdir())+sep));
  await rm(profile,{recursive:true,force:true,maxRetries:10,retryDelay:100});
}
