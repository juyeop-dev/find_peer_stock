import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import { extname, join, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

const frontend = fileURLToPath(new URL("../", import.meta.url));
const browserPath = process.env.BROWSER_PATH ?? [
  "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
  "/usr/bin/chromium", "/usr/bin/google-chrome",
].find(existsSync);
assert.ok(browserPath, "Set BROWSER_PATH to an installed Chromium browser.");
let historyUnavailable = false;
const server = createServer(async (request, response) => {
  const pathname = new URL(request.url, "http://localhost").pathname;
  const relative = pathname.startsWith("/assets/") || pathname.startsWith("/data/") ? pathname.slice(1) : "index.html";
  if (historyUnavailable && pathname.includes("/history/")) return response.writeHead(503).end();
  try {
    const body = await readFile(join(frontend, "dist", relative));
    const mime = { ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".html": "text/html" };
    response.writeHead(200, { "Content-Type": mime[extname(relative)] });
    response.end(body);
  } catch { response.writeHead(404).end(); }
});
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
const origin = `http://127.0.0.1:${server.address().port}`;
const profile = await mkdtemp(join(tmpdir(), "stock-peer-calendar-"));
const browser = spawn(browserPath, ["--headless=new", "--disable-gpu", "--no-first-run", "--no-sandbox",
  "--no-default-browser-check", "--remote-debugging-port=0", `--user-data-dir=${profile}`, "about:blank"],
{ windowsHide: true, stdio: "ignore" });
let socket;
let send;
const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
async function until(predicate, message) {
  const deadline = Date.now() + 15000;
  while (Date.now() < deadline) { if (await predicate()) return; await delay(40); }
  throw new Error(message);
}
const json = async (path) => JSON.parse(await readFile(join(frontend, "dist/data", path), "utf8"));
const format = value => new Intl.NumberFormat("ko-KR").format(value);
try {
  await until(() => existsSync(join(profile, "DevToolsActivePort")), "Browser debugger did not start.");
  const [port] = (await readFile(join(profile, "DevToolsActivePort"), "utf8")).split(/\r?\n/);
  const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  socket = new WebSocket(targets.find(target => target.type === "page").webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    socket.addEventListener("open", resolve, { once: true });
    socket.addEventListener("error", reject, { once: true });
  });
  let sequence = 0;
  const pending = new Map();
  const exceptions = [];
  socket.addEventListener("message", event => {
    const message = JSON.parse(event.data);
    if (message.method === "Runtime.exceptionThrown") exceptions.push(message.params.exceptionDetails);
    const task = pending.get(message.id);
    if (!task) return;
    pending.delete(message.id);
    clearTimeout(task.timeout);
    if (message.error) task.reject(new Error(message.error.message));
    else task.resolve(message.result);
  });
  send = (method, params = {}) => new Promise((resolve, reject) => {
    const id = ++sequence;
    const timeout = setTimeout(() => { pending.delete(id); reject(new Error(`${method} timed out.`)); }, 5000);
    pending.set(id, { resolve, reject, timeout });
    socket.send(JSON.stringify({ id, method, params }));
  });
  await send("Runtime.enable");
  const evaluate = async expression => {
    const result = await send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
    if (result.exceptionDetails) throw new Error(result.exceptionDetails.text);
    return result.result.value;
  };
  const summary = index => evaluate(`document.querySelectorAll('.historySummary article > strong')[${index}]?.innerText`);
  const navigate = async query => {
    await send("Page.navigate", { url: `${origin}/calendar-history?${query}` });
    await until(() => evaluate("document.querySelector('.historySummary') !== null"), "Summary did not load.");
  };
  const highs = await json("new-highs/index.json");
  const turnover = await json("turnover/index.json");
  const reports = highs.reports.filter(item => item.market === "korea");
  const latest = reports.map(item => item.date).sort().at(-1);
  const year = latest.slice(0, 4);
  const month = latest.slice(5, 7);
  const monthly = reports.filter(item => item.date.startsWith(`${year}-${month}`));
  await navigate("market=korea");
  await until(() => evaluate("document.querySelectorAll('.historyStocksTable tbody tr').length > 0"), "Monthly ranking did not load.");
  assert.equal(await summary(0), `${monthly.length}일`);
  assert.equal(await summary(1), `${format(monthly.reduce((sum, item) => sum + item.counts.total, 0))}건`);
  assert.equal(await evaluate("document.querySelectorAll('.historyDay.hasRecords').length"), monthly.length);
  const dailyHref = await evaluate("document.querySelector('.historyDay.hasRecords').getAttribute('href')");
  assert.ok(dailyHref.startsWith("/new-highs?market=korea&date="));
  await evaluate("document.querySelector('.historySectionHeading input').value = ''");
  // Use the native setter to exercise the controlled search input.
  await evaluate(`(() => { const input = document.querySelector('.historySectionHeading input');
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, 'NO_SUCH_STOCK_123');
    input.dispatchEvent(new Event('input', { bubbles: true })); })()`);
  await until(() => evaluate("document.querySelectorAll('.historyStocksTable tbody tr').length === 0"), "Search did not filter.");
  await navigate(`market=korea&view=year&year=${year}`);
  const annualCount = reports.filter(item => item.date.startsWith(year)).reduce((sum, item) => sum + item.counts.total, 0);
  await until(() => evaluate("document.querySelectorAll('.historyStocksTable tbody tr').length > 0"), "Yearly ranking did not load.");
  assert.equal(await summary(1), `${format(annualCount)}건`);
  assert.equal(await evaluate("document.querySelectorAll('.historyMonthGrid button').length"), 12);
  assert.equal(await evaluate("document.querySelector('.historyTotalsTable tbody tr:last-child td:last-child').innerText"), `${format(annualCount)}건`);
  const archive = await json(`new-highs/history/korea/${year}.json`);
  const unique = new Set(archive.months.flatMap(item => item.stocks.map(stock => stock.ticker))).size;
  assert.equal(await summary(3), `${format(unique)}종목`);
  for (const width of [1440, 900, 390, 320]) {
    await send("Emulation.setDeviceMetricsOverride", { width, height: 1000, deviceScaleFactor: 1, mobile: false });
    assert.equal(await evaluate("document.documentElement.scrollWidth > window.innerWidth"), false, `Horizontal overflow at ${width}px.`);
  }
  await send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 1100, deviceScaleFactor: 1, mobile: false });
  const screenshot = await send("Page.captureScreenshot", { format: "png" });
  const screenshotPath = join(tmpdir(), "stock-peer-calendar-history.png");
  await writeFile(screenshotPath, Buffer.from(screenshot.data, "base64"));
  console.log(`Preview: ${screenshotPath}`);
  await evaluate(`document.querySelectorAll('.historyMonthGrid button')[${Number(month) - 1}].click()`);
  await until(() => evaluate("document.querySelector('.historyCalendar') !== null"), "Month drilldown failed.");
  assert.equal(await summary(1), `${format(monthly.reduce((sum, item) => sum + item.counts.total, 0))}건`);
  await send("Page.navigate", { url: new URL(dailyHref, origin).href });
  await until(() => evaluate("document.querySelector('.newHighReportHeading h2') !== null"), "Daily detail navigation failed.");
  for (const market of turnover.markets.map(item => item.id)) {
    const records = turnover.reports.filter(item => item.market === market && item.date.startsWith(year));
    if (!records.length) continue;
    await navigate(`kind=turnover&market=${market}&view=year&year=${year}`);
    await until(() => evaluate("document.querySelectorAll('.historyStocksTable tbody tr').length > 0"), `${market} turnover ranking did not load.`);
    assert.equal(await summary(0), `${records.length}일`);
    assert.equal(await summary(2), `${format(records.reduce((sum, item) => sum + item.count, 0))}건`);
    assert.equal(await evaluate("document.querySelectorAll('.historyTotalsTable tbody tr').length"), 12);
  }
  const emptyMonth = Array.from({ length: 12 }, (_, i) => String(i + 1).padStart(2, "0"))
    .find(value => !reports.some(item => item.date.startsWith(`${year}-${value}`)));
  if (emptyMonth) {
    await navigate(`market=korea&year=${year}&month=${emptyMonth}`);
    await until(() => evaluate("document.querySelector('.historyEmpty') !== null"), "Empty month did not display.");
    assert.equal(await summary(0), "0일");
    assert.equal(await evaluate("document.querySelectorAll('.historyDay.hasRecords').length"), 0);
  }
  historyUnavailable = true;
  await navigate(`market=korea&year=${year}`);
  await until(() => evaluate("document.querySelector('.historyRetry') !== null"), "History error did not display.");
  assert.ok((await summary(1)).includes("건"), "Daily index summaries must survive history failure.");
  historyUnavailable = false;
  await evaluate("document.querySelector('.historyRetry').click()");
  await until(() => evaluate("document.querySelectorAll('.historyStocksTable tbody tr').length > 0"), "History retry did not recover.");
  await navigate("market=unknown&year=invalid&month=99&view=invalid&kind=invalid");
  assert.equal(await summary(0), `${monthly.length}일`);
  assert.deepEqual(exceptions, [], "No browser runtime exceptions.");
  console.log("PASS calendar history: monthly/yearly totals, unique stocks, search, drilldown, six markets, empty periods, retry, invalid URL, 320–1440px layouts.");
} finally {
  if (send && socket?.readyState === WebSocket.OPEN) await send("Browser.close").catch(() => {});
  socket?.close();
  browser.kill();
  server.closeAllConnections();
  await new Promise(resolve => server.close(resolve));
  const resolvedProfile = resolve(profile);
  assert.ok(resolvedProfile.startsWith(resolve(tmpdir()) + sep));
  await rm(resolvedProfile, { recursive: true, force: true, maxRetries: 10, retryDelay: 100 });
}
