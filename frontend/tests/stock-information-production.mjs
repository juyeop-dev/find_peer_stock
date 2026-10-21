import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../../", import.meta.url));
const base = process.env.STOCK_SITE_BASE_URL ?? "https://juyeop-dev.github.io/find_peer_stock";
const rows = (await readFile(join(root, "data/information-audit/results.jsonl"), "utf8")).trim().split("\n").map(JSON.parse);
const routes = ["/semiconductors/000660.KS", "/stocks/2330.TW", ...["korea", "us", "japan", "taiwan", "china", "europe"].map(market => {
  const row = rows.find(row => row.market === market && row.pages.includes("market") && row.history_status === "complete" && row.financial_first?.startsWith("2025"));
  assert.ok(row, `No representative complete stock for ${market}`);
  return `/market-stocks/${encodeURIComponent(row.ticker)}?${new URLSearchParams({market,date:row.date,source:row.source})}`;
})];
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
      try {const body = JSON.parse(message.params.request.postData);if (["information","history"].includes(body.kind)) requests.set(message.params.requestId,body.kind);} catch {}
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
  for (const route of routes) {
    await send("Page.navigate",{url:base+route});
    await until(() => evaluate("Boolean(document.querySelector('.stockHistoryChart .semiChart')) && document.querySelectorAll('.stockInformationPanel table').length >= 2"), `${route} did not load both daily prices and reported financials`);
    assert.equal(await evaluate("document.querySelector('.stockHistoryChart .semiPeriodTabs .active').innerText"),"1년");
    await evaluate("[...document.querySelectorAll('.stockHistoryChart .semiPeriodTabs button')].find(button=>button.innerText==='2025년~').click()");
    const info = await evaluate("({title:document.querySelector('h1').innerText,range:document.querySelector('.stockHistoryChart .semiChart').getAttribute('aria-label'),financials:document.querySelector('.stockInformationPanel').innerText.includes('2025-')})");
    const dates = info.range.match(/\d{4}-\d{2}-\d{2}/g);
    assert.equal(dates.length,2);assert.ok(dates[0] <= "2025-01-01",JSON.stringify(info));assert.ok(info.financials);
    for (const width of [1440,320]) {
      await send("Emulation.setDeviceMetricsOverride",{width,height:1000,deviceScaleFactor:1,mobile:false});
      assert.equal(await evaluate("document.documentElement.scrollWidth > innerWidth"),false,`${route} overflows at ${width}px`);
    }
    console.log(JSON.stringify({route,...info}));
  }
  await send("Page.navigate",{url:base+"/stocks/2330.TW"});
  await until(() => evaluate("Boolean(document.querySelector('.stockInformationPanel table')) && !document.querySelector('.stockInformationPanel button').disabled && !document.querySelector('.stockHistoryChart > button').disabled"), "Initial source requests did not finish");
  for (const [kind,selector] of [["information",".stockInformationPanel button"],["history",".stockHistoryChart > button"]]) {
    const before = statuses.length;
    await evaluate(`document.querySelector(${JSON.stringify(selector)}).click()`);
    await until(() => Promise.resolve(statuses.slice(before).some(item=>item.kind===kind)), `${kind} original request did not return`);
    await until(() => evaluate(`!document.querySelector(${JSON.stringify(selector)}).disabled`), `${kind} refresh did not finish`);
    assert.ok(statuses.slice(before).some(item=>item.kind===kind&&item.status===200), `${kind} provider query failed`);
  }
  assert.deepEqual(exceptions,[]);
  console.log("PASS production: eight detail routes, 2025 start, reported financials, mobile widths, original information/history refresh.");
} finally {
  if (send && socket?.readyState === WebSocket.OPEN) await send("Browser.close").catch(()=>{});
  socket?.close();browser.kill();
  assert.ok(resolve(profile).startsWith(resolve(tmpdir())+sep));
  await rm(profile,{recursive:true,force:true,maxRetries:10,retryDelay:100});
}
