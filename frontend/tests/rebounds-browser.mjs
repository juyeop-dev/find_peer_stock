import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import { mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve, sep } from 'node:path';
const base = process.env.STOCK_SITE_BASE_URL ?? 'http://127.0.0.1:4192';
const basePath = new URL(base).pathname.replace(/\/$/, '');
const executable = ['C:/Program Files/Google/Chrome/Application/chrome.exe', 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', '/usr/bin/google-chrome', '/usr/bin/chromium'].find(existsSync);
assert.ok(executable, 'Chrome or Edge is required');
const profile = await mkdtemp(join(tmpdir(), 'rebounds-browser-'));
const browser = spawn(executable, ['--headless=new', '--disable-gpu', '--no-sandbox', '--no-first-run', '--remote-debugging-port=0', `--user-data-dir=${profile}`, 'about:blank'], { windowsHide: true, stdio: 'ignore' });
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
async function until(check, message) { const end = Date.now() + 45000; while (Date.now() < end) { if (await check()) return; await delay(80); } throw new Error(message); }
let socket, send;
try {
  await until(() => existsSync(join(profile, 'DevToolsActivePort')), 'Browser did not launch');
  const [port] = (await readFile(join(profile, 'DevToolsActivePort'), 'utf8')).split(/\r?\n/);
  const pages = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  socket = new WebSocket(pages.find(page => page.type === 'page').webSocketDebuggerUrl);
  await new Promise(resolve => socket.addEventListener('open', resolve, { once: true }));
  let sequence = 0; const pending = new Map(), exceptions = [];
  socket.addEventListener('message', event => {
    const value = JSON.parse(event.data);
    if (value.method === 'Runtime.exceptionThrown') exceptions.push(value.params.exceptionDetails);
    const task = pending.get(value.id); if (!task) return; pending.delete(value.id); clearTimeout(task.timer);
    value.error ? task.reject(new Error(value.error.message)) : task.resolve(value.result);
  });
  send = (method, params = {}) => new Promise((resolve, reject) => {
    const id = ++sequence, timer = setTimeout(() => { pending.delete(id); reject(new Error(method + ' timeout')); }, 15000);
    pending.set(id, { resolve, reject, timer }); socket.send(JSON.stringify({ id, method, params }));
  });
  const evaluate = async expression => { const result = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true }); if (result.exceptionDetails) throw new Error(JSON.stringify(result.exceptionDetails)); return result.result.value; };
  const navigate = async route => {
    let loaded = false;
    const listener = event => { if (JSON.parse(event.data).method === 'Page.loadEventFired') loaded = true; };
    socket.addEventListener('message', listener);
    const url = basePath && route.startsWith(`${basePath}/`) ? new URL(route, base).href : base + route;
    try { await send('Page.navigate', { url }); await until(() => loaded, 'Page did not load'); } finally { socket.removeEventListener('message', listener); }
  };
  const ready = () => until(() => evaluate("document.querySelectorAll('.reboundBoard').length===2"), 'Rebound groups did not render');
  const click = text => evaluate(`(()=>{const button=[...document.querySelectorAll('button')].find(n=>n.textContent.trim()===${JSON.stringify(text)});if(!button)throw new Error('Missing '+${JSON.stringify(text)});button.click();})()`);
  await send('Runtime.enable'); await send('Page.enable');
  await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1100, deviceScaleFactor: 1, mobile: false });
  await navigate('/rebounds'); await ready();
  const index = await (await fetch(base + '/data/rebounds/index.json')).json(), actual = index.reports[0];
  assert.ok(actual, 'A real collected session must be available');
  assert.equal(await evaluate("document.querySelectorAll('.reboundBoard li').length"), actual.count);
  assert.equal(await evaluate("document.querySelector('.reboundBoard.kospi h3 span').textContent"), `(${actual.counts.KOSPI ?? 0})`);
  assert.equal(await evaluate("document.querySelector('.reboundBoard.kosdaq h3 span').textContent"), `(${actual.counts.KOSDAQ ?? 0})`);
  assert.ok(await evaluate("[...document.querySelectorAll('.siteNavLinks a')].some(n=>n.textContent==='일일 반등'&&n.getAttribute('aria-current')==='page')"));
  for (const width of [1440, 390, 320]) {
    await send('Emulation.setDeviceMetricsOverride', { width, height: 1100, deviceScaleFactor: 1, mobile: false });
    await delay(100);
    assert.equal(await evaluate('document.documentElement.scrollWidth>document.documentElement.clientWidth'), false, `Overflow at ${width}`);
    await evaluate("document.querySelector('.turnoverReport').scrollIntoView({block:'start'})");
    const shot = await send('Page.captureScreenshot', { format: 'png' }), folder = new URL('../../data/tmp_rebounds/ui/', import.meta.url);
    await mkdir(folder, { recursive: true }); await writeFile(new URL(`rebounds-${width}.png`, folder), Buffer.from(shot.data, 'base64'));
  }
  console.log(`PASS real ${actual.date} archive (${actual.count} stocks) and 1440/390/320px layouts`);

  assert.ok(index.reports.some(row => row.date === '2018-01-02'), 'The historical archive must start in 2018');
  for (const year of ['2018', '2020', '2025', '2026']) {
    const saved = index.reports.find(row => row.date.startsWith(year) && row.count > 0 && row.date < '2026-11-04');
    assert.ok(saved, `Missing ${year} historical report`);
    await navigate(`/rebounds?date=${saved.date}`); await ready();
    assert.equal(await evaluate("document.querySelectorAll('.reboundBoard li').length"), saved.count);
    assert.ok(await evaluate("document.querySelector('.turnoverSources').textContent.includes('KRX daily data')"));
    assert.ok(await evaluate("document.querySelector('.turnoverReport').textContent.includes('당시 상장 종목')"));
    const link = await evaluate("document.querySelector('.reboundBoard li a').getAttribute('href')");
    assert.ok(link.includes(`date=${saved.date}`));
  }
  const recordedZero = index.reports.find(row => row.count === 0);
  assert.ok(recordedZero, 'A real recorded zero-result day must exist');
  await navigate(`/rebounds?date=${recordedZero.date}`); await ready();
  assert.equal(await evaluate("document.querySelectorAll('.reboundEmpty').length"), 2);
  assert.equal(await evaluate("document.querySelector('.turnoverReportHeading>span').textContent"), '0종목');
  console.log('PASS real 2018/2020/2025/2026 history, dated stock links, source explanation and recorded zero day');

  const stock = (ticker, name, exchange, price, low, cap, change_pct = 0) => ({ ticker, name, exchange, price, low, market_cap: cap, change_pct, rebound_pct: (price / low - 1) * 100, currency: 'KRW', market_cap_currency: 'KRW', sector: 'Electronic Technology', industry: 'Semiconductors' });
  const report = { schema_version: 1, market: 'korea', date: '2026-11-02', rules: index.rules, sources: [], source_metadata: { provider: 'browser fixture', fetched_at: '2026-11-02T07:00:00Z', session: 'daily', scanned_symbols: 2638, excluded: {} }, entries: [stock('009830.KS', '한화솔루션', 'KOSPI', 108, 100, 5e12), stock('039030.KQ', '이오테크닉스', 'KOSDAQ', 105, 100, 1e12), stock('006400.KS', '삼성SDI', 'KOSPI', 110, 100, 5e12, 1)] };
  const zero = { ...report, date: '2026-11-03', entries: [] };
  const fixtures = new Map([
    ['/data/rebounds/index.json', { ...index, refresh: { status: 'updated', message: '' }, reports: [{ date: zero.date, count: 0, counts: {}, fetched_at: zero.source_metadata.fetched_at }, { date: report.date, count: 3, counts: { KOSPI: 2, KOSDAQ: 1 }, fetched_at: report.source_metadata.fetched_at }] }],
    ['/data/rebounds/korea/2026_11/2026-11-02.json', report], ['/data/rebounds/korea/2026_11/2026-11-03.json', zero],
  ]);
  let failRequests = false;
  socket.addEventListener('message', event => {
    const value = JSON.parse(event.data); if (value.method !== 'Fetch.requestPaused') return;
    const { requestId, request } = value.params, fixture = fixtures.get(new URL(request.url).pathname.slice(basePath.length));
    const response = fixture
      ? send('Fetch.fulfillRequest', { requestId, responseCode: failRequests ? 503 : 200, responseHeaders: [{ name: 'Content-Type', value: 'application/json' }], body: Buffer.from(JSON.stringify(fixture)).toString('base64') })
      : send('Fetch.continueRequest', { requestId });
    // A navigation aborts outstanding requests before their paused callbacks finish.
    void response.catch(error => { if (!error.message.includes('Invalid InterceptionId')) throw error; });
  });
  await send('Fetch.enable', { patterns: [{ urlPattern: '*data/rebounds/*' }] });
  await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1100, deviceScaleFactor: 1, mobile: false });
  await navigate('/rebounds?date=2026-11-02'); await ready();
  assert.equal(await evaluate("document.querySelector('.reboundBoard.kospi li a').textContent"), '삼성SDI', 'Stocks must be ordered by rebound descending');
  await evaluate("(()=>{const input=document.querySelector('[aria-label=\"반등 종목 검색\"]');Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,'한화');input.dispatchEvent(new Event('input',{bubbles:true}));})()");
  await until(() => evaluate("document.querySelectorAll('.reboundBoard li').length===1"), 'Search failed');
  await evaluate("Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async text=>{window.copiedRebounds=text;}}})");
  await click('반등 목록 복사');
  assert.ok((await evaluate('window.copiedRebounds')).includes('KOSPI 2개 | 시총 5조 이상 | 반등 8% 이상'));
  assert.ok((await evaluate('window.copiedRebounds')).includes('• 이오테크닉스 +5.00% | 105원 (+0.00%)'), 'Copy must include the whole report even while searching');
  const detail = await evaluate("document.querySelector('.reboundBoard li a').getAttribute('href')");
  assert.ok(detail.includes('source=rebounds') && detail.includes('date=2026-11-02'));
  await navigate(detail);
  await until(() => evaluate("document.querySelector('.marketStockSnapshot')?.textContent.includes('당일 저가 대비 반등률')"), 'Stock detail did not preserve rebound source');
  assert.ok((await evaluate("document.querySelector('.semiBreadcrumb a').getAttribute('href')")).includes('/rebounds?date=2026-11-02'));

  await navigate('/rebounds?date=2026-11-03'); await ready();
  assert.equal(await evaluate("document.querySelectorAll('.reboundBoard li').length"), 0);
  assert.equal(await evaluate("document.querySelectorAll('.reboundEmpty').length"), 2, 'Recorded zero-result days need their own empty states');
  await navigate('/rebounds?date=2026-11-04');
  await until(() => evaluate("document.querySelector('.turnoverEmpty')?.textContent.includes('아직 없습니다')"), 'Unrecorded day confused with zero results');
  assert.equal(await evaluate("document.querySelectorAll('.reboundBoard').length"), 0);
  await navigate('/rebounds?date=2026-11-01');
  await until(() => evaluate("document.querySelector('.turnoverEmpty')?.textContent.includes('휴장일')"), 'Weekend did not show closure');
  await navigate('/rebounds?date=2026-02-30');
  await until(() => evaluate("document.querySelector('.turnoverReport')?.textContent.includes('조회 날짜가 올바르지 않습니다')"), 'Invalid date did not show an error');
  await navigate('/rebounds?date=2026-11-02'); await ready();
  failRequests = true;
  await click('새로고침');
  await until(() => evaluate("document.querySelector('.reboundPage').textContent.includes('(503)')"), 'Refresh failure did not show an error');
  assert.equal(await evaluate("document.querySelectorAll('.reboundBoard li').length"), 3, 'Refresh failure discarded prior report');
  assert.equal(exceptions.length, 0, JSON.stringify(exceptions));
  console.log('PASS search, full report copy, stock detail/back link, recorded zero, unrecorded/closed/invalid dates, and failure retention');
} finally {
  if (send && socket?.readyState === WebSocket.OPEN) await send('Browser.close').catch(() => {});
  socket?.close(); browser.kill();
  assert.ok(resolve(profile).startsWith(resolve(tmpdir()) + sep));
  await rm(profile, { recursive: true, force: true, maxRetries: 10, retryDelay: 100 });
}
