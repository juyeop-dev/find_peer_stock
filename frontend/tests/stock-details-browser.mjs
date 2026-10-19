import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import { extname, join, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

const frontend = fileURLToPath(new URL("../", import.meta.url));
const browserPath = process.env.BROWSER_PATH ?? ["C:/Program Files/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", "/usr/bin/chromium", "/usr/bin/google-chrome"].find(existsSync);
assert.ok(browserPath, "Set BROWSER_PATH to an installed Chromium browser.");
const readJson = async path => JSON.parse(await readFile(join(frontend, "dist/data", path), "utf8"));
const index = await readJson("new-highs/index.json");
const base = { name: "NAVER", ticker: "035420.KS", exchange: "KOSPI", currency: "KRW", category: "인터넷 서비스",
  high_type: "52_week", reason: "업종: 인터넷 서비스", session_close: 200000, change_pct: 1.2, market_cap: 30e12, market_cap_currency: "KRW" };
const semi = { ...base, name: "제주반도체", ticker: "080220.KQ", exchange: "KOSDAQ", category: "반도체" };
const report = (market, entries) => ({ schema_version: 1, market, date: "2026-10-19", entries });
const reports = [report("korea", [base, semi]), report("japan", [{ ...base, ticker: "6503.T", name: "미쓰비시전기", exchange: "TSE", currency: "JPY", session_close: 5000 }]),
  report("us", [{ ...base, ticker: "AAPL", name: "Apple", exchange: "NASDAQ", currency: "USD", session_close: 220 }])];
const turnoverEntries = [base, semi].map((stock, i) => ({ ...stock, rank: i + 1, price: stock.session_close,
  sector: "전자 기술", industry: stock.category, turnover: (2 - i) * 1e9 }));
const fixtures = new Map([
  ["/data/new-highs/index.json", { ...index, reports: reports.map(item => ({ market: item.market, date: item.date,
    counts: { total: item.entries.length, high_52_week: item.entries.length, high_all_time: 0 }, exchanges: {} })) }],
  ["/data/turnover/index.json", { ...index, reports: [{ market: "korea", date: "2026-10-19", count: 2, total_turnover: 3e9, currency: "KRW" }] }],
  ["/data/turnover/korea/2026_10/2026-10-19.json", report("korea", turnoverEntries)],
  ...reports.map(item => [`/data/new-highs/${item.market}/2026-10-19.json`, item]),
]);
for (const [ticker, currency] of [["035420.KS", "KRW"], ["6503.T", "JPY"], ["AAPL", "USD"]]) {
  fixtures.set(`/data/stock-history/${ticker}.json`, { ticker, currency, source: "Daily history test fixture", fetched_at: new Date().toISOString(), first_trade_date: "2000-01-01",
    prices: Array.from({ length: 380 }, (_, i) => [new Date(Date.UTC(2025, 9, 5 + i)).toISOString().slice(0, 10), 100 + i, 100 + i]) });
}
const server = createServer(async (request, response) => {
  const pathname = new URL(request.url, "http://localhost").pathname;
  if (fixtures.has(pathname)) { response.writeHead(200, { "Content-Type": "application/json" }).end(JSON.stringify(fixtures.get(pathname))); return; }
  try {
    const relative = pathname.startsWith("/assets/") || pathname.startsWith("/data/") ? pathname.slice(1) : "index.html";
    const body = await readFile(join(frontend, "dist", relative));
    const mime = { ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".html": "text/html" };
    response.writeHead(200, { "Content-Type": mime[extname(relative)] }).end(body);
  } catch { response.writeHead(404).end(); }
});
await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
const origin = `http://127.0.0.1:${server.address().port}`;
const profile = await mkdtemp(join(tmpdir(), "stock-peer-details-"));
const browser = spawn(browserPath, ["--headless=new", "--disable-gpu", "--no-sandbox", "--no-first-run",
  "--no-default-browser-check", "--remote-debugging-port=0", `--user-data-dir=${profile}`, "about:blank"], { windowsHide: true, stdio: "ignore" });
let socket;
let send;
let failWidgets = false;
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
async function until(predicate, message) {
  const deadline = Date.now() + 15000;
  while (Date.now() < deadline) { if (await predicate()) return; await delay(40); }
  throw new Error(message);
}
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
    if (message.method === "Fetch.requestPaused") {
      const { requestId } = message.params;
      if (failWidgets) void send("Fetch.fulfillRequest", { requestId, responseCode: 503, body: "" });
      else {
        const javascript = `(() => { const script = document.currentScript; if (!script?.parentElement) return;
          const config = JSON.parse(script.textContent); (window.widgetConfigs ??= []).push(config);
          const iframe = document.createElement('iframe'); iframe.style.width='100%'; iframe.style.height='100%';
          script.parentElement.appendChild(iframe); setTimeout(() => iframe.src='data:text/html,widget', 0); })();`;
        void send("Fetch.fulfillRequest", { requestId, responseCode: 200,
          responseHeaders: [{ name: "Content-Type", value: "text/javascript" }, { name: "Cache-Control", value: "no-store" }], body: Buffer.from(javascript).toString("base64") });
      }
      return;
    }
    const task = pending.get(message.id);
    if (!task) return;
    pending.delete(message.id);
    clearTimeout(task.timeout);
    if (message.error) task.reject(new Error(message.error.message)); else task.resolve(message.result);
  });
  send = (method, params = {}, sessionId) => new Promise((resolve, reject) => {
    const id = ++sequence;
    const timeout = setTimeout(() => { pending.delete(id); reject(new Error(`${method} timed out.`)); }, 5000);
    pending.set(id, { resolve, reject, timeout });
    socket.send(JSON.stringify({ id, method, params, ...(sessionId ? { sessionId } : {}) }));
  });
  await send("Runtime.enable");
  await send("Fetch.enable", { patterns: [{ urlPattern: "https://s3.tradingview.com/external-embedding/*" }] });
  const evaluate = async expression => {
    const result = await send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
    if (result.exceptionDetails) throw new Error(result.exceptionDetails.text);
    return result.result.value;
  };
  const navigate = async (path, selector) => {
    await send("Page.navigate", { url: `${origin}${path}` });
    await until(() => evaluate(`document.querySelector(${JSON.stringify(selector)}) !== null`), `${path} did not load ${selector}.`);
  };
  const showChart = async () => {
    await until(() => evaluate("document.querySelector('.marketFullChartButton') !== null"), "Full chart control did not appear.");
    await evaluate("document.querySelector('.marketFullChartButton').click()");
  };
  const calendar = "/new-highs?market=korea&date=2026-10-19&exchange=all";
  await navigate(calendar, ".newHighStockDetailLink");
  assert.equal(await evaluate("document.querySelectorAll('.newHighStockDetailLink').length"), 2);
  const genericLink = await evaluate("[...document.querySelectorAll('.newHighStockDetailLink')].find(a => a.innerText.includes('NAVER')).getAttribute('href')");
  const semiLink = await evaluate("[...document.querySelectorAll('.newHighStockDetailLink')].find(a => a.innerText.includes('제주반도체')).getAttribute('href')");
  assert.ok(genericLink.startsWith("/market-stocks/035420.KS?"));
  assert.ok(semiLink.startsWith("/semiconductors/080220.KQ?"));
  assert.equal(await evaluate("document.querySelectorAll('.newHighTickerLink[target=_blank]').length"), 2);
  await evaluate("document.querySelector('.newHighStockDetailLink').click()");
  await until(() => evaluate("document.querySelector('.marketStockPage h1')?.innerText === 'NAVER'"), "New-high click did not open stock detail.");
  await until(() => evaluate("document.querySelector('.marketStockChart .semiChart') !== null"), "Native one-year daily chart did not load.");
  assert.equal(await evaluate("document.querySelector('.stockHistoryChart .semiPeriodTabs .active').innerText"), "1년");
  assert.ok(await evaluate("document.querySelector('.marketStockChart .semiChart').getAttribute('aria-label').includes('2025-10')"));
  await showChart();
  await until(() => evaluate("document.querySelectorAll('.marketWidget iframe').length === 2 && document.querySelectorAll('.marketWidgetLoading').length === 0"), "Widgets did not become ready.");
  assert.equal(await evaluate("document.querySelector('.semiQuoteHero strong').innerText"), "200,000 KRW");
  assert.equal(await evaluate("document.querySelector('.semiBreadcrumb a').getAttribute('href')"), calendar);
  assert.equal(await evaluate("window.widgetConfigs.every(item => item.symbol === 'KRX:035420')"), true);
  assert.equal(await evaluate("window.widgetConfigs.filter(item => item.interval === 'D').every(item => item.range === '12M')"), true);
  for (const width of [1440, 900, 390, 320]) {
    await send("Emulation.setDeviceMetricsOverride", { width, height: 1000, deviceScaleFactor: 1, mobile: false });
    assert.equal(await evaluate("document.documentElement.scrollWidth > window.innerWidth"), false, `Horizontal overflow at ${width}px.`);
  }
  await send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false });
  await evaluate("document.querySelector('.semiBreadcrumb a').click()");
  await until(() => evaluate("document.querySelector('.newHighStockDetailLink') !== null"), "Return to calendar failed.");
  assert.equal(await evaluate("location.pathname + location.search"), calendar);
  await navigate(semiLink, ".semiDetailHeader h1");
  assert.equal(await evaluate("document.querySelector('.semiDetailHeader h1').innerText"), "제주반도체");
  assert.ok(await evaluate("document.querySelector('.semiMetricsPanel') !== null && document.querySelector('.semiFinanceGrid') !== null"));
  assert.equal(await evaluate("document.querySelector('.stockHistoryChart .semiPeriodTabs .active').innerText"), "1년");
  assert.equal(await evaluate("document.querySelector('.semiBreadcrumb a').getAttribute('href')"), calendar);
  await navigate("/turnover?market=korea&date=2026-10-19", ".turnoverCompany");
  assert.equal(await evaluate("document.querySelectorAll('.turnoverCompany:not([target])').length"), 2);
  await evaluate("document.querySelector('.turnoverCompany').click()");
  await until(() => evaluate("document.querySelector('.marketStockPage h1')?.innerText === 'NAVER'"), "Turnover click did not open stock detail.");
  assert.ok(await evaluate("document.querySelector('.marketStockSnapshot').innerText.includes('거래대금 순위')"));
  assert.equal(await evaluate("document.querySelector('.semiBreadcrumb a').getAttribute('href')"), "/turnover?market=korea&date=2026-10-19");
  for (const [market, ticker, currency, symbol] of [["japan", "6503.T", "JPY", "TSE:6503"], ["us", "AAPL", "USD", "NASDAQ:AAPL"]]) {
    await navigate(`/market-stocks/${ticker}?market=${market}&date=2026-10-19&source=new-highs`, ".marketStockPage h1");
    await showChart();
    await until(() => evaluate("document.querySelectorAll('.marketWidget iframe').length === 2"), `${market} embeds did not load.`);
    assert.ok((await evaluate("document.querySelector('.semiQuoteHero strong').innerText")).includes(currency));
    assert.ok(await evaluate(`window.widgetConfigs.every(item => item.symbol === ${JSON.stringify(symbol)})`));
    await send("Page.reload");
    await until(() => evaluate("document.querySelector('.marketStockPage h1') !== null"), "Shared detail URL did not survive reload.");
  }
  await navigate("/stocks/6503.T", ".quoteSummary");
  await until(() => evaluate("document.querySelector('.stockHistoryChart .semiChart') !== null"), "Peer detail must also display a native chart.");
  assert.equal(await evaluate("document.querySelector('.stockHistoryChart .semiPeriodTabs .active').innerText"), "1년");
  failWidgets = true;
  await navigate(genericLink, ".marketStockPage h1");
  await showChart();
  await until(() => evaluate("document.querySelectorAll('.marketWidgetError').length === 2"), "Embed failure did not show fallback.");
  assert.ok(await evaluate("document.querySelector('.marketStockActions a') !== null"));
  failWidgets = false;
  await evaluate("document.querySelector('.marketWidgetError button').click()");
  await until(() => evaluate("document.querySelector('.marketWidget-chart iframe') !== null && !document.querySelector('.marketWidget-chart .marketWidgetError')"), "Embed retry failed.");
  await navigate("/market-stocks/AAPL?market=us&date=2026-02-30", ".notice");
  assert.equal(await evaluate("document.querySelectorAll('.marketWidget').length"), 0);
  await navigate("/market-stocks/MISSING?market=us&date=2026-10-19", ".notice");
  assert.ok(await evaluate("document.querySelector('.notice').innerText.includes('찾을 수 없습니다')"));
  assert.deepEqual(exceptions, []);
  if (process.env.STOCK_DETAIL_LIVE_WIDGETS === "1") {
    await send("Fetch.disable");
    await send("Network.enable");
    await send("Network.setCacheDisabled", { cacheDisabled: true });
    await send("Network.clearBrowserCache");
    await navigate("/market-stocks/AAPL?market=us&date=2026-10-19", ".marketStockPage h1");
    await showChart();
    await until(() => evaluate("document.querySelectorAll('.marketWidget iframe').length === 2 && document.querySelectorAll('.marketWidgetLoading').length === 0"), "Live TradingView widgets did not load.");
    const iframeUrls = await evaluate("[...document.querySelectorAll('.marketWidget iframe')].map(frame => frame.src)");
    assert.equal(iframeUrls.every(value => new URL(value).hostname === "www.tradingview-widget.com"), true);
    assert.equal(iframeUrls.every(value => decodeURIComponent(new URL(value).hash).includes("NASDAQ:AAPL")), true);
    await evaluate("document.querySelector('.marketStockFinancials').scrollIntoView()");
    await until(async () => (await send("Target.getTargets")).targetInfos.filter(item => item.type === "iframe" && item.url.includes("tradingview-widget.com")).length === 2,
      "Both live widget documents did not become available.");
    const targets = await send("Target.getTargets");
    for (const target of targets.targetInfos.filter(item => item.type === "iframe" && item.url.includes("tradingview-widget.com"))) {
      const { sessionId } = await send("Target.attachToTarget", { targetId: target.targetId, flatten: true });
      await until(async () => {
        const result = await send("Runtime.evaluate", { expression: "document.body.innerText", returnByValue: true }, sessionId);
        return /AAPL|Apple|애플/.test(result.result.value ?? "");
      }, "Live widget did not resolve the selected company.");
    }
    // Chart data continues loading after the iframe document's load event.
    await delay(2000);
    await evaluate("window.scrollTo(0, 0)");
    const screenshot = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: true,
      clip: { x: 0, y: 0, width: 1440, height: 2100, scale: 1 } });
    const screenshotPath = join(tmpdir(), "stock-peer-stock-detail.png");
    await writeFile(screenshotPath, Buffer.from(screenshot.data, "base64"));
    console.log(`Live widget preview: ${screenshotPath}`);
    for (const [market, ticker] of [["korea", "035420.KS"], ["japan", "6503.T"]]) {
      await navigate(`/market-stocks/${ticker}?market=${market}&date=2026-10-19`, ".marketStockPage h1");
      await showChart();
      await until(() => evaluate("document.querySelectorAll('.marketWidget iframe').length === 2 && document.querySelectorAll('.marketWidgetLoading').length === 0"), `${market} live widgets did not load.`);
      await evaluate("document.querySelector('.marketStockFinancials').scrollIntoView()");
      await delay(1500);
      const marketTargets = await send("Target.getTargets");
      for (const target of marketTargets.targetInfos.filter(item => item.type === "iframe" && item.url.includes("tradingview-widget.com"))) {
        const { sessionId } = await send("Target.attachToTarget", { targetId: target.targetId, flatten: true });
        const result = await send("Runtime.evaluate", { expression: "document.body.innerText", returnByValue: true }, sessionId);
        console.log(`Live ${market} ${new URL(target.url).pathname}: ${String(result.result.value).slice(0, 180).replaceAll('\n', ' ')}`);
      }
    }
  }
  console.log("PASS stock details: both calendar entry points, existing semiconductor screen, all-market symbols, return context, reload, widgets and retry, invalid dates, mobile layouts.");
} finally {
  if (send && socket?.readyState === WebSocket.OPEN) await send("Browser.close").catch(() => {});
  socket?.close(); browser.kill(); server.closeAllConnections();
  await new Promise(resolve => server.close(resolve));
  const resolvedProfile = resolve(profile);
  assert.ok(resolvedProfile.startsWith(resolve(tmpdir()) + sep));
  await rm(resolvedProfile, { recursive: true, force: true, maxRetries: 10, retryDelay: 100 });
}
