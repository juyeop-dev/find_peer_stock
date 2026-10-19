import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import { extname, join, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

const frontend = fileURLToPath(new URL("../", import.meta.url));
const readJson = async path => JSON.parse(await readFile(join(frontend, "dist/data", path), "utf8"));
const semi = await readJson("semiconductor/index.json");
const semiTickers = new Set(semi.stocks.map(stock => stock.ticker));
const highIndex = await readJson("new-highs/index.json");
const turnoverIndex = await readJson("turnover/index.json");
const koreaHigh = highIndex.reports.filter(item => item.market === "korea").map(item => item.date).sort().at(-1);
const koreaTurnover = turnoverIndex.reports.filter(item => item.market === "korea").map(item => item.date).sort().at(-1);
const highReport = await readJson(`new-highs/korea/${koreaHigh}.json`);
const turnoverReport = await readJson(`turnover/korea/${koreaTurnover.slice(0, 7).replace("-", "_")}/${koreaTurnover}.json`);
const general = turnoverReport.entries.find(stock => !semiTickers.has(stock.ticker));
assert.ok(general);
const requests = [];
let failSource = false;
let partialSource = false;
const sourceAt = "2099-01-01T00:00:00Z";
function quote(ticker) {
  const currency = /\.(KS|KQ)$/.test(ticker) ? "KRW" : ticker.endsWith(".T") ? "JPY" : "USD";
  return { ticker, price: 987654, previous_close: 980000, change: 7654, change_pct: 0.78, currency,
    source: "Original test provider", fetched_at: sourceAt, provider_time: sourceAt, market_time: sourceAt,
    status: "ok", market_cap: 1234500000000, market_cap_currency: currency, market_cap_usd: 900000000 };
}
const server = createServer(async (request, response) => {
  const pathname = new URL(request.url, "http://localhost").pathname;
  try {
    const relative = pathname.startsWith("/assets/") || pathname.startsWith("/data/") ? pathname.slice(1) : "index.html";
    const body = await readFile(join(frontend, "dist", relative));
    const mime = { ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".html": "text/html" };
    response.writeHead(200, { "Content-Type": mime[extname(relative)] }).end(body);
  } catch { response.writeHead(404).end(); }
});
await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
const origin = `http://127.0.0.1:${server.address().port}`;
const browserPath = process.env.BROWSER_PATH ?? ["C:/Program Files/Google/Chrome/Application/chrome.exe", "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", "/usr/bin/chromium", "/usr/bin/google-chrome"].find(existsSync);
assert.ok(browserPath);
const profile = await mkdtemp(join(tmpdir(), "stock-peer-live-refresh-"));
const browser = spawn(browserPath, ["--headless=new", "--disable-gpu", "--no-sandbox", "--no-first-run", "--no-default-browser-check", "--remote-debugging-port=0", `--user-data-dir=${profile}`, "about:blank"], { windowsHide: true, stdio: "ignore" });
let socket, send;
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
async function until(predicate, message, limit = 15000) {
  const deadline = Date.now() + limit;
  while (Date.now() < deadline) { if (await predicate()) return; await delay(30); }
  throw new Error(message);
}
try {
  await until(() => existsSync(join(profile, "DevToolsActivePort")), "Browser debugger did not start.");
  const [port] = (await readFile(join(profile, "DevToolsActivePort"), "utf8")).split(/\r?\n/);
  const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  socket = new WebSocket(targets.find(target => target.type === "page").webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { socket.addEventListener("open", resolve, { once: true }); socket.addEventListener("error", reject, { once: true }); });
  let sequence = 0;
  const pending = new Map(), exceptions = [];
  socket.addEventListener("message", event => {
    const message = JSON.parse(event.data);
    if (message.method === "Runtime.exceptionThrown") exceptions.push(message.params.exceptionDetails);
    if (message.method === "Fetch.requestPaused") {
      const { requestId, request: intercepted } = message.params;
      void (async () => {
        if (intercepted.url.includes("s3.tradingview.com")) {
          await send("Fetch.fulfillRequest", { requestId, responseCode: 503, body: "" }); return;
        }
        const headers = [{ name: "Content-Type", value: "application/json" }, { name: "Cache-Control", value: "no-store" },
          { name: "Access-Control-Allow-Origin", value: origin }, { name: "Access-Control-Allow-Methods", value: "POST, OPTIONS" }, { name: "Access-Control-Allow-Headers", value: "Content-Type" }];
        if (intercepted.method === "OPTIONS") { await send("Fetch.fulfillRequest", { requestId, responseCode: 204, responseHeaders: headers }); return; }
        const body = JSON.parse(intercepted.postData);
        requests.push(body);
        await delay(80);
        let response;
        if (failSource) response = { error: "원본 조회 테스트 실패 · 기존 값 유지" };
        else if (body.kind === "quotes" || body.kind === "details") {
          const rejected = partialSource ? body.stocks.slice(0, 1) : [];
          const stocks = partialSource ? body.stocks.slice(1) : body.stocks;
          response = { fetched_at: sourceAt, errors: rejected.map(stock => ({ ticker: stock.ticker, message: "부분 실패" })), items: stocks.map(stock => body.kind === "quotes" ? quote(stock.ticker) : {
            ticker: stock.ticker, quote: quote(stock.ticker), fetched_at: sourceAt, warnings: [],
            history: [{ date: "2026-10-16", close: 980000, adjusted_close: 980000, volume: 100 }, { date: "2026-10-19", close: 987654, adjusted_close: 987654, volume: 200 }],
            metrics: { marketValue: "1조 2,345억", per: "11.11배" },
            annual_financials: [{ period: "2025.12", type: "annual", revenue: 777777, operating_income: 12345, net_income: 1000 }],
            quarterly_financials: [], recent_financials: { basis: "annual", period_label: "2025년 결산 연간", periods: ["2025.12"], latest_reported_period: null, revenue: 777777, operating_income: 12345, reason: null },
          }) };
        } else if (body.kind === "scan") {
          response = { ...structuredClone(body.source === "new-highs" ? highReport : turnoverReport), live_fetched_at: sourceAt };
        } else if (body.kind === "credit") response = { fetched_at: sourceAt, history: [{ date: "2026-10-19", total: 40000000, kospi: 30000000, kosdaq: 10000000 }] };
        else throw new Error(`Unexpected original request ${body.kind}`);
        await send("Fetch.fulfillRequest", { requestId, responseCode: failSource ? 502 : 200, responseHeaders: headers, body: Buffer.from(JSON.stringify(response)).toString("base64") });
      })().catch(error => exceptions.push(String(error)));
      return;
    }
    const task = pending.get(message.id);
    if (!task) return;
    pending.delete(message.id); clearTimeout(task.timeout);
    if (message.error) task.reject(new Error(message.error.message)); else task.resolve(message.result);
  });
  send = (method, params = {}) => new Promise((resolve, reject) => {
    const id = ++sequence;
    const timeout = setTimeout(() => { pending.delete(id); reject(new Error(`${method} timed out.`)); }, 5000);
    pending.set(id, { resolve, reject, timeout }); socket.send(JSON.stringify({ id, method, params }));
  });
  await send("Runtime.enable");
  await send("Fetch.enable", { patterns: [{ urlPattern: "https://find-peer-stock-live-api.find-peer-stock-juyeop.workers.dev/*" }, { urlPattern: "https://s3.tradingview.com/external-embedding/*" }] });
  const evaluate = async expression => {
    const result = await send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
    if (result.exceptionDetails) throw new Error(result.exceptionDetails.text);
    return result.result.value;
  };
  async function navigate(path, selector) {
    await send("Page.navigate", { url: `${origin}${path}` });
    await until(() => evaluate(`document.querySelector(${JSON.stringify(selector)}) && document.querySelector('.dataRefreshStatus button')?.disabled === false`), `${path} did not become ready.`);
  }
  async function refresh(limit = 15000) {
    await evaluate("document.querySelector('.dataRefreshStatus button').click()");
    await until(() => evaluate("document.querySelector('.sourceFetchedAt') && document.querySelector('.dataRefreshStatus button')?.disabled === false"), "Original refresh did not finish.", limit);
  }
  const pages = [
    ["/", ".stockTile", "quotes"], ["/stocks/000660.KS", ".quoteSummary", "quotes"],
    ["/semiconductors", ".semiStockPriceTable", "details"], ["/semiconductors/trends", ".semiTrendTable", "details"],
    ["/semiconductors/000660.KS", ".semiDetailHeader", "details"],
    [`/new-highs?market=korea&date=${koreaHigh}`, ".newHighStockDetailLink", "scan"],
    [`/turnover?market=korea&date=${koreaTurnover}`, ".turnoverCompany", "scan"],
    ["/calendar-history?market=korea&view=year&year=2026", ".historyStocksTable tbody tr", "quotes"],
    [`/market-stocks/${general.ticker}?market=korea&date=${koreaTurnover}&source=turnover`, ".marketStockPage h1", "details"],
    ["/credit-balance", ".creditHeadline", "credit"],
  ];
  for (const [path, selector, kind] of pages) {
    await navigate(path, selector);
    const start = requests.length;
    await refresh();
    const sent = requests.slice(start);
    assert.ok(sent.some(request => request.kind === kind), `${path} must fetch its original provider, not only published JSON.`);
    assert.equal(sent.some(request => request.kind === "details" && request.stocks.length > 4), false);
    assert.equal(sent.some(request => request.kind === "quotes" && request.stocks.length > 12), false);
    if (path === "/semiconductors" || path === "/semiconductors/trends") assert.equal(new Set(sent.flatMap(request => request.stocks ?? []).map(stock => stock.ticker)).size, semi.stocks.length);
    if (path.startsWith("/market-stocks")) assert.ok(await evaluate("document.body.innerText.includes('원본 조회') && document.body.innerText.includes('777,777')"));
    console.log(`PASS original refresh ${path}`);
  }
  await navigate("/semiconductors/000660.KS", ".semiDetailHeader");
  await refresh();
  const unchanged = await evaluate("document.querySelector('.semiQuoteHero strong').innerText");
  const start = requests.length;
  await refresh();
  assert.ok(requests.length > start, "Repeated clicks must each contact the original source.");
  await evaluate("window.dispatchEvent(new Event('focus'))");
  await delay(200);
  assert.equal(await evaluate("document.querySelector('.semiQuoteHero strong').innerText"), unchanged, "Automatic JSON polling must not overwrite the freshly queried price with an older snapshot.");
  failSource = true;
  await evaluate("document.querySelector('.dataRefreshStatus button').click()");
  await until(() => evaluate("document.querySelector('.notice')?.innerText.includes('실패') && document.querySelector('.dataRefreshStatus button').disabled === false"), "Original failure was not surfaced.");
  assert.equal(await evaluate("document.querySelector('.semiQuoteHero strong').innerText"), unchanged);
  failSource = false;
  await navigate("/stocks/000660.KS", ".quoteSummary");
  partialSource = true;
  await refresh();
  assert.ok(await evaluate("document.querySelector('.notice')?.innerText.includes('기존 값')"));
  partialSource = false;
  assert.deepEqual(exceptions, []);
  if (process.env.STOCK_LIVE_REFRESH_NETWORK === "1") {
    await send("Fetch.disable");
    await navigate("/semiconductors/000660.KS", ".semiDetailHeader");
    await refresh(90000);
    // Fresh test overrides are document-local and cleared by full navigation.
    const actual = await evaluate("({ price: document.querySelector('.semiQuoteHero strong').innerText, fetched: document.querySelector('.sourceFetchedAt').innerText })");
    assert.ok(!actual.fetched.includes("2099"));
    console.log(`LIVE source response ${JSON.stringify(actual)}`);
    await navigate("/semiconductors", ".semiStockPriceTable");
    await evaluate(`window.__liveResults = []; window.__originalFetch = window.fetch;
      window.fetch = async (...args) => {
        const response = await window.__originalFetch(...args);
        if (String(args[0]).includes('/refresh')) {
          try { const payload = await response.clone().json(); window.__liveResults.push({
            items: (payload.items ?? []).map(item => ({ ticker: item.ticker, warnings: item.warnings, price: item.quote?.price })), errors: payload.errors ?? [], error: payload.error
          }); } catch { window.__liveResults.push({ error: 'Invalid provider response' }); }
        }
        return response;
      };`);
    await refresh(180000);
    const responses = await evaluate("window.__liveResults");
    const successful = responses.flatMap(response => response.items ?? []);
    const problems = responses.filter(response => response.error || response.errors?.length || response.items?.some(item => item.warnings?.length));
    if (problems.length) console.log(`LIVE field warnings ${JSON.stringify(problems)}`);
    assert.equal(new Set(successful.filter(item => item.price > 0).map(item => item.ticker)).size, semi.stocks.length, "Every semiconductor should return a fresh quote.");
    console.log(`LIVE all ${semi.stocks.length} semiconductor stocks refreshed`);
  }
  console.log("PASS all pages, original requests on every click, bounded batches, stale-poll protection, full and partial failure retention.");
} finally {
  if (send && socket?.readyState === WebSocket.OPEN) await send("Browser.close").catch(() => {});
  socket?.close(); browser.kill(); server.closeAllConnections();
  await new Promise(resolve => server.close(resolve));
  const target = resolve(profile); assert.ok(target.startsWith(resolve(tmpdir()) + sep));
  await rm(target, { recursive: true, force: true, maxRetries: 10, retryDelay: 100 });
}
