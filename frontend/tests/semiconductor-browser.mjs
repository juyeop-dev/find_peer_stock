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
  async function checkChartPointerAlignment() {
    for (const width of [1600, 900, 390]) {
      await send("Emulation.setDeviceMetricsOverride", { width, height: 1000, deviceScaleFactor: 1, mobile: false });
      for (const fraction of [0, 0.25, 0.5, 0.75, 1]) {
        const target = await evaluate(`(() => {
          const svg = document.querySelector('.semiChart svg');
          svg.scrollIntoView({ block: 'center' });
          const vertices = [...svg.querySelector('.semiLine').getAttribute('d').matchAll(/[ML]([\\d.-]+),([\\d.-]+)/g)];
          const vertex = vertices[Math.round((vertices.length - 1) * ${fraction})];
          const point = new DOMPoint(Number(vertex[1]), Number(vertex[2]));
          const chart = svg.parentElement;
          chart.scrollLeft = 0;
          const before = point.matrixTransform(svg.getScreenCTM());
          chart.scrollLeft = Math.max(0, before.x - chart.getBoundingClientRect().left - chart.clientWidth / 2);
          const screen = point.matrixTransform(svg.getScreenCTM());
          return { x: screen.x, y: screen.y, scrollLeft: chart.scrollLeft };
        })()`);
        await send("Input.dispatchMouseEvent", { type: "mouseMoved", x: target.x, y: target.y });
        const dot = await evaluate("(() => { const rect = document.querySelector('.semiDot').getBoundingClientRect(); return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 }; })()");
        assert.ok(Math.abs(dot.x - target.x) < 1.5 && Math.abs(dot.y - target.y) < 1.5,
          `Chart pointer and dot differ at width ${width}, fraction ${fraction}: pointer=${JSON.stringify(target)}, dot=${JSON.stringify(dot)}`);
      }
    }
    // Change the range while the pointer is still over the last point.
    await evaluate("[...document.querySelectorAll('.semiPeriodTabs button')].find(button => button.innerText === '7일').click()");
    assert.ok(await evaluate("Boolean(document.querySelector('.semiChartReadout strong')?.innerText)"), "Changing the range must preserve a valid hover point.");
    await send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false });
  }
  await send("Page.enable");
  await send("Page.navigate", { url: `${origin}/semiconductors` });
  await until(() => evaluate("document.querySelectorAll('.semiStockPriceTable tbody tr').length > 0"), "Semiconductor stocks did not load.");
  assert.equal(await evaluate("document.querySelectorAll('.semiStockPriceTable tbody tr').length"), 96);
  assert.deepEqual(await evaluate("[...document.querySelectorAll('.semiStockPriceTable th')].map(item => item.innerText.replace(/[↕↑↓]/g, '').trim())"),
    ["종목", "대분류", "중분류", "소분류", "시장", "가격", "시가총액", "기준일", "등락률", "30일 수익률", "최근 1년 매출", "최근 1년 영업이익", "실적 기간"]);
  assert.equal(await evaluate("[...document.querySelectorAll('.semiStockPriceTable .semiFinancialPeriod')].every(cell => cell.innerText.includes('2025년 3Q~2026년 2Q') && cell.innerText.includes('TTM'))"), true);
  const caps = () => evaluate("[...document.querySelectorAll('.semiStockPriceTable tbody tr')].map(row => row.cells[6].innerText.trim())");
  const clickSort = (label) => evaluate(`[...document.querySelectorAll('.semiStockPriceTable .semiSortButton')].find(button => button.innerText.includes(${JSON.stringify(label)})).click()`);
  const numericRows = async (table, column) => {
    const values = await evaluate(`[...document.querySelectorAll('.${table} tbody tr')].map(row => row.cells[${column}].innerText.trim())`);
    return values.map((value) => {
      const units = [...value.matchAll(/(-?[\d,]+(?:\.\d+)?)\s*(조|억|만)/g)];
      if (units.length) return units.reduce((sum, [, number, unit]) => sum + Number(number.replaceAll(",", "")) * { 조: 1e12, 억: 1e8, 만: 1e4 }[unit], 0);
      return Number.parseFloat(value.replaceAll(",", ""));
    });
  };
  const assertOrder = (values, direction) => {
    const available = values.filter(Number.isFinite);
    assert.deepEqual(available, [...available].sort((a, b) => direction === "asc" ? a - b : b - a));
    assert.ok(values.slice(available.length).every(Number.isNaN), "Missing values must sort last.");
  };
  await clickSort("시가총액");
  assert.equal(await evaluate("document.querySelector('.semiStockPriceTable th[aria-sort=descending]')?.innerText.includes('시가총액')"), true);
  const descendingCaps = await caps();
  await clickSort("시가총액");
  assert.equal(await evaluate("document.querySelector('.semiStockPriceTable th[aria-sort=ascending]')?.innerText.includes('시가총액')"), true);
  assert.deepEqual(await caps(), descendingCaps.reverse());
  for (const [label, column] of [["등락률", 8], ["30일 수익률", 9], ["최근 1년 매출", 10], ["최근 1년 영업이익", 11]]) {
    await clickSort(label);
    assert.equal(await evaluate(`document.querySelector('.semiStockPriceTable th[aria-sort=descending]')?.innerText.includes(${JSON.stringify(label)})`), true);
    assertOrder(await numericRows("semiStockPriceTable", column), "desc");
    await clickSort(label);
    assert.equal(await evaluate(`document.querySelector('.semiStockPriceTable th[aria-sort=ascending]')?.innerText.includes(${JSON.stringify(label)})`), true);
    assertOrder(await numericRows("semiStockPriceTable", column), "asc");
  }
  const selectFilter = (index, value) => evaluate(`(() => { const select = document.querySelectorAll('.semiFilters select')[${index}]; select.value = ${JSON.stringify(value)}; select.dispatchEvent(new Event('change', { bubbles: true })); })()`);
  await selectFilter(0, "핵심 연관 테마");
  await selectFilter(1, "인터페이스");
  await selectFilter(2, "CXL");
  assert.equal(await evaluate("document.querySelectorAll('.semiStockPriceTable tbody tr').length"), 4);
  assert.equal(await evaluate("[...document.querySelectorAll('.semiStockPriceTable tbody tr')].some(row => row.innerText.includes('삼성전자') && row.cells[3].innerText === 'CXL')"), true);
  await send("Page.navigate", { url: `${origin}/semiconductors/005930.KS` });
  await until(() => evaluate("document.querySelectorAll('.semiMemberships > span').length > 0"), "Stock memberships did not load.");
  assert.equal(await evaluate("document.querySelectorAll('.semiMemberships > span').length"), 5);
  assert.equal(await evaluate("[...document.querySelectorAll('.semiPage .semiTable tbody tr')].some(row => row.cells[0]?.innerText === '2026-10-12' && row.cells[1]?.innerText === '251,000원')"), true);
  await send("Page.navigate", { url: `${origin}/semiconductors/031980.KQ` });
  await until(() => evaluate("document.querySelector('.semiBusinessPanel')?.innerText.includes('Descum')"), "PSK Holdings business details did not load.");
  assert.equal(await evaluate("document.querySelectorAll('.semiMemberships > span').length"), 3);
  assert.equal(await evaluate("document.querySelector('.semiQuoteHero strong')?.innerText.includes('원')"), true);
  assert.equal(await evaluate("document.querySelectorAll('.semiBusinessSources a').length"), 2);
  assert.equal(await evaluate("document.querySelector('.semiMemberships')?.innerText.includes('전공정')"), false);
  assert.equal(await evaluate("document.querySelector('.semiRecentFinancials .semiFinancialPeriod')?.innerText"), "2025년 3Q~2026년 2Q");
  assert.deepEqual(await evaluate("[...document.querySelectorAll('.semiRecentFinancialValues strong')].map(item => item.innerText)"), ["2,173억", "784억"]);
  await checkChartPointerAlignment();
  await send("Page.navigate", { url: `${origin}/semiconductors/trends` });
  await until(() => evaluate("document.querySelectorAll('.semiConstituentTable tbody tr').length > 0"), "Semiconductor trends did not load.");
  assert.equal(await evaluate("document.querySelectorAll('.semiTrendTable tbody tr').length"), 6);
  assert.equal(await evaluate("[...document.querySelectorAll('.semiTrendTable tbody tr')].find(row => row.cells[0].innerText === '칩 생산')?.cells[3].innerText"), "3개");
  assert.deepEqual(await evaluate("[...document.querySelectorAll('.semiTrendTable th')].map(item => item.innerText.replace(/[↕↑↓]/g, '').trim())"),
    ["대분류", "중분류", "소분류", "종목 수", "7일", "30일", "90일", "180일", "360일"]);
  assert.deepEqual(await evaluate("[...document.querySelectorAll('.semiConstituentTable th')].map(item => item.innerText.replace(/[↕↑↓]/g, '').trim())"),
    ["종목", "대분류", "중분류", "소분류", "시장", "현재가", "시가총액", "등락률", "30일 수익률", "최근 1년 매출", "최근 1년 영업이익", "실적 기간"]);
  assert.equal(await evaluate("document.querySelector('.semiConstituentTable tbody tr')?.cells[5].innerText.includes('원')"), true);
  assert.equal(await evaluate("document.querySelector('.semiConstituentTable tbody tr')?.cells[6].innerText.includes('억')"), true);
  const selectedSector = await evaluate("document.querySelector('.semiTrendTable tr.selected')?.innerText");
  for (const [label, column] of [["종목 수", 3], ["7일", 4], ["30일", 5], ["90일", 6], ["180일", 7], ["360일", 8]]) {
    const button = `[...document.querySelectorAll('.semiTrendTable .semiSortButton')].find(item => item.innerText.includes(${JSON.stringify(label)}))`;
    await evaluate(`${button}.click()`);
    assert.equal(await evaluate(`document.querySelector('.semiTrendTable th[aria-sort=descending]')?.innerText.includes(${JSON.stringify(label)})`), true);
    assertOrder(await numericRows("semiTrendTable", column), "desc");
    await evaluate(`${button}.click()`);
    assert.equal(await evaluate(`document.querySelector('.semiTrendTable th[aria-sort=ascending]')?.innerText.includes(${JSON.stringify(label)})`), true);
    assertOrder(await numericRows("semiTrendTable", column), "asc");
  }
  assert.equal(await evaluate("document.querySelector('.semiTrendTable tr.selected')?.innerText"), selectedSector);
  for (const [label, column] of [["현재가", 5], ["시가총액", 6], ["등락률", 7], ["30일 수익률", 8], ["최근 1년 매출", 9], ["최근 1년 영업이익", 10]]) {
    const button = `[...document.querySelectorAll('.semiConstituentTable .semiSortButton')].find(item => item.innerText.includes(${JSON.stringify(label)}))`;
    await evaluate(`${button}.click()`);
    assert.equal(await evaluate(`document.querySelector('.semiConstituentTable th[aria-sort=descending]')?.innerText.includes(${JSON.stringify(label)})`), true);
    assertOrder(await numericRows("semiConstituentTable", column), "desc");
    await evaluate(`${button}.click()`);
    assert.equal(await evaluate(`document.querySelector('.semiConstituentTable th[aria-sort=ascending]')?.innerText.includes(${JSON.stringify(label)})`), true);
    assertOrder(await numericRows("semiConstituentTable", column), "asc");
  }
  await selectFilter(0, "minor");
  await selectFilter(1, "핵심 연관 테마");
  assert.equal(await evaluate("document.querySelectorAll('.semiTrendTable tbody tr').length"), 11);
  await evaluate("[...document.querySelectorAll('.semiTrendTable tbody tr')].find(row => row.cells[2].innerText === 'CXL').cells[2].querySelector('button').click()");
  assert.equal(await evaluate("document.querySelectorAll('.semiConstituentTable tbody tr').length"), 4);
  await checkChartPointerAlignment();
  await send("Page.navigate", { url: `${origin}/credit-balance` });
  await until(() => evaluate("document.querySelectorAll('.creditTable tbody tr').length > 0"), "Credit balances did not load.");
  assert.equal(await evaluate("document.querySelector('.creditTable tbody tr')?.cells[0].innerText"), "2026-10-12");
  assert.equal(await evaluate("document.querySelector('.creditSummaryStrip button.active')?.innerText.includes('34.289조원')"), true);
  await evaluate("document.querySelectorAll('.creditSummaryStrip button')[2].click()");
  assert.equal(await evaluate("document.querySelector('.creditHeadline strong')?.innerText"), "7.573조원");
  assert.equal(await evaluate("document.querySelector('.semiChartReadout strong')?.innerText"), "2026-10-12");
  await checkChartPointerAlignment();
  console.log("PASS semiconductor and credit balance pages");
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
