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
  await send("Page.navigate", { url: `${origin}/semiconductors` });
  await until(() => evaluate("document.querySelectorAll('.semiStockPriceTable tbody tr').length > 0"), "Semiconductor stocks did not load.");
  assert.deepEqual(await evaluate("[...document.querySelectorAll('.semiStockPriceTable th')].map(item => item.innerText.replace(/[↕↑↓]/g, '').trim())"),
    ["종목", "대분류", "중분류", "소분류", "시장", "가격", "기준일", "등락률", "시가총액", "30일 수익률"]);
  const caps = () => evaluate("[...document.querySelectorAll('.semiStockPriceTable tbody tr')].map(row => row.cells[8].innerText.trim())");
  const clickSort = (label) => evaluate(`[...document.querySelectorAll('.semiStockPriceTable .semiSortButton')].find(button => button.innerText.includes(${JSON.stringify(label)})).click()`);
  await clickSort("시가총액");
  assert.equal(await evaluate("document.querySelector('.semiStockPriceTable th[aria-sort=descending]')?.innerText.includes('시가총액')"), true);
  const descendingCaps = await caps();
  await clickSort("시가총액");
  assert.equal(await evaluate("document.querySelector('.semiStockPriceTable th[aria-sort=ascending]')?.innerText.includes('시가총액')"), true);
  assert.deepEqual(await caps(), descendingCaps.reverse());
  for (const label of ["등락률", "30일 수익률"]) {
    await clickSort(label);
    assert.equal(await evaluate(`document.querySelector('.semiStockPriceTable th[aria-sort=descending]')?.innerText.includes(${JSON.stringify(label)})`), true);
    await clickSort(label);
    assert.equal(await evaluate(`document.querySelector('.semiStockPriceTable th[aria-sort=ascending]')?.innerText.includes(${JSON.stringify(label)})`), true);
  }
  await send("Page.navigate", { url: `${origin}/semiconductors/trends` });
  await until(() => evaluate("document.querySelectorAll('.semiConstituentTable tbody tr').length > 0"), "Semiconductor trends did not load.");
  assert.deepEqual(await evaluate("[...document.querySelectorAll('.semiConstituentTable th')].map(item => item.innerText.trim())"),
    ["종목", "대분류", "중분류", "소분류", "시장", "현재가", "등락률", "시가총액", "30일 수익률"]);
  assert.equal(await evaluate("document.querySelector('.semiConstituentTable tbody tr')?.cells[5].innerText.includes('원')"), true);
  assert.equal(await evaluate("document.querySelector('.semiConstituentTable tbody tr')?.cells[7].innerText.includes('억')"), true);
  console.log("PASS semiconductor classification, quote details, and sortable returns/market cap");
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
