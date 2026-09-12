import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import { extname, join, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

// Run after a production build: node tests/polling-browser.mjs
// Uses an installed Chromium browser; no extra npm dependencies are required.
const frontend = fileURLToPath(new URL("../", import.meta.url));
const browserPath = process.env.BROWSER_PATH ?? [
  "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
  "/usr/bin/chromium", "/usr/bin/chromium-browser", "/usr/bin/google-chrome"
].find(existsSync);
assert.ok(browserPath, "Set BROWSER_PATH to an installed Chromium browser.");
const fixtures = new Map();
const requests = [];
const siteIndex = JSON.parse(await readFile(join(frontend, "public/data/index.json"), "utf8"));
const stock = JSON.parse(await readFile(join(frontend, "public/data/stocks/3026.TW.json"), "utf8"));
const archive = JSON.parse(await readFile(join(frontend, "public/data/new-highs/index.json"), "utf8"));
fixtures.set("/data/index.json", { ...siteIndex, generated_at: new Date().toISOString() });
fixtures.set("/data/stocks/3026.TW.json", stock);
fixtures.set("/data/new-highs/index.json", { ...archive, reports: [] });
let failStock = false;
const server = createServer(async (request, response) => {
  const pathname = new URL(request.url, "http://localhost").pathname;
  if (pathname.startsWith("/data/")) requests.push(request.url);
  if (pathname === "/data/stocks/3026.TW.json" && failStock) {
    response.writeHead(503).end();
    return;
  }
  if (fixtures.has(pathname)) {
    response.writeHead(200, { "Content-Type": "application/json" });
    response.end(JSON.stringify(fixtures.get(pathname)));
    return;
  }
  try {
    const relative = pathname.startsWith("/assets/") ? pathname.slice(1) : "index.html";
    const body = await readFile(join(frontend, "dist", relative));
    const mime = { ".js": "text/javascript", ".css": "text/css", ".html": "text/html" };
    response.writeHead(200, { "Content-Type": mime[extname(relative)] });
    response.end(body);
  } catch {
    response.writeHead(404).end();
  }
});
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
const origin = `http://127.0.0.1:${server.address().port}`;
const profile = await mkdtemp(join(tmpdir(), "stock-peer-polling-"));
const browser = spawn(browserPath, [
  "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
  "--remote-debugging-port=0", `--user-data-dir=${profile}`, "about:blank"
], { windowsHide: true, stdio: "ignore" });
const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
async function until(predicate, message) {
  const deadline = Date.now() + 12_000;
  while (Date.now() < deadline) {
    if (await predicate()) return;
    await delay(25);
  }
  throw new Error(message);
}
let socket;
let send;
try {
  await until(() => existsSync(join(profile, "DevToolsActivePort")), "Browser debugger did not start.");
  const [port] = (await readFile(join(profile, "DevToolsActivePort"), "utf8")).split(/\r?\n/);
  const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`, { signal: AbortSignal.timeout(5_000) })).json();
  const target = targets.find((target) => target.type === "page");
  socket = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    const timeout = setTimeout(() => reject(new Error("Debugger connection timed out.")), 5_000);
    socket.addEventListener("open", () => { clearTimeout(timeout); resolve(); }, { once: true });
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
  const contains = (text) => evaluate(`document.body.innerText.includes(${JSON.stringify(text)})`);
  await send("Page.enable");
  await send("Page.addScriptToEvaluateOnNewDocument", { source: `
    const nativeTimeout = window.setTimeout;
    window.setTimeout = (fn, ms, ...args) => nativeTimeout(fn, ms === 60000 ? 100 : ms, ...args);
    const nativeFetch = window.fetch;
    window.__fetches = [];
    window.fetch = (url, options) => {
      window.__fetches.push({ url, cache: options?.cache });
      return nativeFetch(url, options);
    };
  ` });

  await send("Page.navigate", { url: origin });
  await until(() => contains("관심 종목"), "Home did not load.");
  fixtures.set("/data/index.json", {
    ...siteIndex, generated_at: new Date().toISOString(),
    stocks: [{ ...siteIndex.stocks[0], name_kr: "자동 갱신 검증 종목", is_target: true }]
  });
  await until(() => contains("자동 갱신 검증 종목"), "Home did not pick up changed index automatically.");
  assert.equal(await evaluate("window.__fetches.every(item => item.cache === 'no-store' && item.url.includes('?t='))"), true);
  console.log("PASS home picks up new data and every request bypasses caching");

  await send("Page.navigate", { url: `${origin}/stocks/3026.TW` });
  await until(() => contains(stock.company.name_kr), "Stock did not load.");
  const changed = structuredClone(stock);
  changed.peer_groups[0].peers[0].company.name_kr = "Peer만 변경 검증";
  // Keep parent quote and generated_at unchanged to catch partial-comparison regressions.
  fixtures.set("/data/stocks/3026.TW.json", changed);
  await until(() => contains("Peer만 변경 검증"), "Peer-only change did not appear automatically.");
  changed.generated_at = new Date(Date.now() - 25 * 60_000).toISOString();
  changed.quote.status = "stale";
  changed.quote.refresh_status = "error";
  fixtures.set("/data/stocks/3026.TW.json", changed);
  await until(() => contains("데이터 생성 후 20분 이상"), "Old generated data warning missing.");
  await until(() => contains("마지막으로 조회한 가격"), "Stale quote notice missing.");
  failStock = true;
  await until(() => contains("503"), "Refresh failure notice missing.");
  assert.equal(await contains("Peer만 변경 검증"), true, "Refresh failure discarded existing data.");
  changed.generated_at = new Date().toISOString();
  changed.quote.status = "ok";
  changed.quote.refresh_status = "fetched";
  failStock = false;
  await until(async () => !(await contains("503")) && !(await contains("데이터 생성 후 20분 이상")), "Stock did not recover after failed refresh.");
  changed.quote.status = "error";
  changed.quote.price = null;
  changed.quote.refresh_status = "not_fetched";
  await until(() => contains("미조회"), "A quote that was not fetched is shown as a successful request.");
  assert.equal(await evaluate("document.querySelector('.sourceMeta').innerText.includes('가격 조회 성공')"), false);
  console.log("PASS peer-only updates, data age/stale notices, retained data and automatic recovery");

  await send("Page.navigate", { url: `${origin}/new-highs` });
  await until(() => contains("아직 등록된 신고가 기록이 없습니다"), "Archive empty state did not load.");
  const report = {
    schema_version: 1, market: "korea", date: "2026-09-11", entries: [{
      ticker: "TEST.KS", name: "새 기록 자동 갱신 검증", exchange: "KOSPI", category: "테스트",
      high_type: "52_week", reason: "브라우저 회귀 검증용 기록"
    }]
  };
  fixtures.set("/data/new-highs/korea/2026-09-11.json", report);
  fixtures.set("/data/new-highs/index.json", { ...archive, reports: [{
    market: "korea", date: report.date, counts: { total: 1, high_52_week: 1, high_all_time: 0 },
    exchanges: { KOSPI: { total: 1, high_52_week: 1, high_all_time: 0 } }
  }] });
  await until(() => contains("새 기록 자동 갱신 검증"), "New archive report was not discovered automatically.");
  report.entries[0].reason = "기존 날짜 내용 자동 수정 검증";
  await until(() => contains("기존 날짜 내용 자동 수정 검증"), "Existing archive report did not refresh.");
  assert.equal(await contains("데이터 생성 후 20분 이상"), false, "Curated archive should not warn about data age.");
  assert.ok(requests.every((url) => url.includes("?t=")));
  console.log("PASS archive discovers new dates and updates selected reports without reloading");
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
