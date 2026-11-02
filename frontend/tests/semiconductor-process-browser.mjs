import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import { extname, join, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

// Run after npm run build: node tests/semiconductor-browser.mjs
const frontend = fileURLToPath(new URL("../", import.meta.url));
const browserPath = process.env.BROWSER_PATH ?? [
  "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
  "/usr/bin/chromium", "/usr/bin/chromium-browser", "/usr/bin/google-chrome"
].find(existsSync);
assert.ok(browserPath, "Set BROWSER_PATH to an installed Chromium browser.");

const server = createServer(async (request, response) => {
  const pathname = new URL(request.url, "http://localhost").pathname;
  const relative = pathname.startsWith("/assets/") || pathname.startsWith("/data/") ? pathname.slice(1) : "index.html";
  try {
    const body = await readFile(join(frontend, "dist", relative));
    const mime = { ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".html": "text/html" };
    response.writeHead(200, { "Content-Type": mime[extname(relative)] });
    response.end(body);
  } catch {
    response.writeHead(404).end();
  }
});
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
const origin = `http://127.0.0.1:${server.address().port}`;
const profile = await mkdtemp(join(tmpdir(), "stock-peer-semiconductor-"));
const browser = spawn(browserPath, [
  "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
  "--remote-debugging-port=0", `--user-data-dir=${profile}`, "about:blank"
], { windowsHide: true, stdio: "ignore" });
let socket;
let send;
const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
async function until(predicate, message) {
  const deadline = Date.now() + 12_000;
  while (Date.now() < deadline) {
    if (await predicate()) return;
    await delay(25);
  }
  throw new Error(message);
}

try {
  await until(() => existsSync(join(profile, "DevToolsActivePort")), "Browser debugger did not start.");
  const [port] = (await readFile(join(profile, "DevToolsActivePort"), "utf8")).split(/\r?\n/);
  const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`, { signal: AbortSignal.timeout(5_000) })).json();
  socket = new WebSocket(targets.find((target) => target.type === "page").webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    socket.addEventListener("open", resolve, { once: true });
    socket.addEventListener("error", reject, { once: true });
  });
  let sequence = 0;
  const pending = new Map();
  socket.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    const task = pending.get(message.id);
    if (!task) return;
    pending.delete(message.id);
    clearTimeout(task.timeout);
    if (message.error) task.reject(new Error(message.error.message));
    else task.resolve(message.result);
  });
  send = (method, params = {}) => new Promise((resolve, reject) => {
    const id = ++sequence;
    const timeout = setTimeout(() => { pending.delete(id); reject(new Error(`${method} timed out.`)); }, 5_000);
    pending.set(id, { resolve, reject, timeout });
    socket.send(JSON.stringify({ id, method, params }));
  });
  const evaluate = async (expression) => {
    const result = await send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
    if (result.exceptionDetails) throw new Error(result.exceptionDetails.text);
    return result.result.value;
  };
  await send("Page.enable");
  const expected = JSON.parse(await readFile(join(frontend, "public/data/semiconductor/index.json"), "utf8"));
  const review = JSON.parse(await readFile(join(frontend, "../data/semiconductor/reviews/2026-11-02-process-image.json"), "utf8"));
  const failures = [];
  socket.addEventListener("message", (event) => {
    const msg = JSON.parse(event.data);
    if (msg.method === "Runtime.exceptionThrown") failures.push(msg.params.exceptionDetails.text);
  });
  await send("Runtime.enable");
  await send("Page.navigate", { url: `${origin}/semiconductors` });
  await until(() => evaluate("document.querySelectorAll('.semiStockPriceTable tbody tr').length === 114"), "114 companies did not load");
  const setFilter = (index, value) => evaluate(`(() => { const el = document.querySelectorAll('.semiFilters select')[${index}]; el.value = ${JSON.stringify(value)}; el.dispatchEvent(new Event('change', {bubbles:true})); })()`);
  const codes = () => evaluate("[...document.querySelectorAll('.semiStockLink span')].map(el => el.innerText).sort()");
  for (const process of review.processes) {
    await setFilter(0, process.major ?? "전공정 소부장");
    await setFilter(1, process.middle);
    await setFilter(2, process.minor);
    assert.deepEqual(await codes(), process.members.map(ticker => ticker.slice(0, 6)).sort(), process.minor);
  }
  await setFilter(0, "");
  for (const change of review.name_changes) {
    await evaluate(`(() => { const el = document.querySelector('.semiSearch input'); Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(el, ${JSON.stringify(change.original)}); el.dispatchEvent(new Event('input', {bubbles:true})); })()`);
    assert.deepEqual(await codes(), [change.ticker.slice(0, 6)], change.original);
  }
  await evaluate("document.querySelector('.semiClassificationReview').open = true");
  assert.ok(await evaluate("document.querySelector('.semiClassificationReview').innerText.includes('에이티세미콘')"));
  for (const width of [1440, 390, 320]) {
    await send("Emulation.setDeviceMetricsOverride", {width, height: 900, deviceScaleFactor: 1, mobile: width < 500});
    assert.equal(await evaluate("document.documentElement.scrollWidth > innerWidth"), false, `overview overflow ${width}`);
  }
  for (const company of review.additions) {
    await send("Page.navigate", {url: `${origin}/semiconductors/${company.ticker}`});
    await until(() => evaluate(`document.querySelector('.semiDetailHeader')?.innerText.includes(${JSON.stringify(company.ticker)})`), company.ticker);
    assert.ok(await evaluate("document.querySelector('.semiBusinessPanel')?.innerText.length > 30"));
    assert.ok(await evaluate("document.querySelectorAll('.semiBusinessSources a').length > 0"));
    assert.ok(await evaluate("document.querySelector('.semiMemberships')?.innerText.length > 10"));
    assert.ok(await evaluate("document.querySelectorAll('.semiPage .semiTable tbody tr').length > 0"));
    assert.ok(await evaluate("document.querySelector('.semiQuoteHero strong')?.innerText.includes('원')"));
    assert.ok(await evaluate("document.querySelector('.semiRecentFinancials')?.innerText.includes('TTM')"));
    await evaluate("document.querySelector('[data-chart-view=archive]').click()");
    await until(() => evaluate("Boolean(document.querySelector('.stockHistoryChart svg'))"), `${company.ticker} chart`);
    assert.equal(await evaluate("document.documentElement.scrollWidth > innerWidth"), false, `${company.ticker} overflow`);
  }
  await send("Page.navigate", {url: `${origin}/semiconductors/trends`});
  await until(() => evaluate("document.querySelectorAll('.semiTrendTable tbody tr').length > 0"), "Trends did not load");
  const actualMajorCounts = await evaluate("Object.fromEntries([...document.querySelectorAll('.semiTrendTable tbody tr')].map(row => [row.cells[0].innerText, parseInt(row.cells[3].innerText)]))");
  const majorCounts = {};
  for (const stock of expected.stocks) for (const major of new Set(stock.classifications.map(item => item.major))) majorCounts[major] = (majorCounts[major] ?? 0) + 1;
  assert.deepEqual(actualMajorCounts, majorCounts, "Repeated process roles must not multiply major membership");
  await setFilter(0, "minor");
  await setFilter(1, "전공정 소부장");
  await evaluate("[...document.querySelectorAll('.semiTrendTable tbody tr')].find(row => row.cells[2].innerText === '증착 · ALD').querySelector('button').click()");
  assert.deepEqual(await codes(), ["036930", "084370", "240810"]);
  for (const width of [1440, 390]) {
    await send("Emulation.setDeviceMetricsOverride", {width, height:900, deviceScaleFactor:1, mobile:width < 500});
    assert.equal(await evaluate("document.documentElement.scrollWidth > innerWidth"), false, `trends overflow ${width}`);
  }
  assert.deepEqual(failures, []);
  console.log("PASS: 38 process filters, 7 historical-name searches, 12 new details/quotes/financials/charts, unique trend counts, PC/mobile layouts");
} finally {
  if (send && socket?.readyState === WebSocket.OPEN) await send("Browser.close").catch(() => {});
  socket?.close();
  browser.kill();
  server.closeAllConnections();
  await new Promise((resolve) => server.close(resolve));
  const resolvedProfile = resolve(profile);
  assert.ok(resolvedProfile.startsWith(resolve(tmpdir()) + sep));
  await rm(resolvedProfile, { recursive: true, force: true, maxRetries: 10, retryDelay: 100 });
}
