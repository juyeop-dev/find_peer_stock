import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {existsSync} from 'node:fs';
import {mkdtemp, readFile, writeFile, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join, resolve, sep} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createServer} from 'vite';
import {staticDataFixture} from './static-data-fixture.mjs';

const root = fileURLToPath(new URL('../', import.meta.url));
const browserPath = process.env.BROWSER_PATH ?? ['C:/Program Files/Google/Chrome/Application/chrome.exe', 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', '/usr/bin/chromium'].find(existsSync);
assert.ok(browserPath, 'Chromium is required for actual responsive browser validation');
const fixture = await staticDataFixture();
const profile = await mkdtemp(join(tmpdir(), 'history-policy-browser-'));
const vite = await createServer({root, configLoader: 'runner', define: {'import.meta.env.VITE_DATA_BASE_URL': JSON.stringify(fixture.base+'/a')}, cacheDir: join(profile, 'vite-cache'), server: {host: '127.0.0.1', port: 0}, logLevel: 'error'});
await vite.listen();
const base = `http://127.0.0.1:${vite.httpServer.address().port}`;
const browser = spawn(browserPath, ['--headless=new', '--disable-gpu', '--no-sandbox', '--no-first-run', '--no-default-browser-check', '--remote-debugging-port=0', `--user-data-dir=${profile}`, 'about:blank'], {windowsHide: true, stdio: 'ignore'});
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
async function until(predicate, message) {
  const deadline = Date.now() + 45000;
  while (Date.now() < deadline) {if (await predicate()) return; await delay(100);}
  throw new Error(message);
}
let socket, send;
const failures = [], measurements = [];
try {
  await until(() => existsSync(join(profile, 'DevToolsActivePort')), 'Chromium did not start');
  const [port] = (await readFile(join(profile, 'DevToolsActivePort'), 'utf8')).split(/\r?\n/);
  const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  socket = new WebSocket(targets.find(target => target.type === 'page').webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {socket.addEventListener('open', resolve, {once: true}); socket.addEventListener('error', reject, {once: true});});
  let sequence = 0;
  const pending = new Map();
  socket.addEventListener('message', event => {
    const message = JSON.parse(event.data);
    if (message.method === 'Runtime.exceptionThrown') failures.push(message.params.exceptionDetails);
    const task = pending.get(message.id);
    if (!task) return;
    pending.delete(message.id); clearTimeout(task.timer);
    message.error ? task.reject(new Error(message.error.message)) : task.resolve(message.result);
  });
  send = (method, params = {}) => new Promise((resolve, reject) => {
    const id = ++sequence, timer = setTimeout(() => {pending.delete(id); reject(new Error(`${method} timeout`));}, 10000);
    pending.set(id, {resolve, reject, timer}); socket.send(JSON.stringify({id, method, params}));
  });
  const evaluate = async expression => {
    const value = await send('Runtime.evaluate', {expression, returnByValue: true, awaitPromise: true});
    if (value.exceptionDetails) throw new Error(JSON.stringify(value.exceptionDetails));
    return value.result.value;
  };
  await send('Runtime.enable');
  await send('Page.navigate', {url: `${base}/tests/static-data-harness.html`});
  await until(() => evaluate("typeof window.runStaticDataTests === 'function'"), 'Static harness did not load');
  const staticResult = await evaluate(`window.runStaticDataTests(${JSON.stringify(fixture.base)})`);
  assert.equal(staticResult.result, 'PASS'); assert.equal(staticResult.crossOrigin, true);
  await send('Page.navigate', {url: `${base}/tests/history-policy-harness.html?remote`});
  await until(() => evaluate("Boolean(document.querySelector('.stockHistoryChart .semiPeriodTabs button') && document.querySelector('.creditPage .semiPeriodTabs button'))"), 'Historical period controls did not render');
  const originalPrices = await evaluate('window.readPublishedFixture()');
  assert.equal(originalPrices.history[0].date, '2013-12-30');
  assert.equal(originalPrices.history[1].date, '2014-01-02');
  assert.equal(originalPrices.history[1].close, 71);
  await until(() => evaluate("document.querySelector('.stockHistoryChart .semiLine') && !document.querySelector('.stockHistoryChart .loadingSpinner')"), 'Remote price line did not load');
  for (const width of [1440, 390, 320]) {
    await send('Emulation.setDeviceMetricsOverride', {width, height: 1100, deviceScaleFactor: 1, mobile: false});
    await delay(200);
    const state = await evaluate(`(() => {
      const chart = [...document.querySelectorAll('.stockHistoryChart .semiPeriodTabs button')];
      const credit = [...document.querySelectorAll('.creditPage .semiPeriodTabs button')];
      chart.find(button => button.textContent === '2014년~').click();
      credit.find(button => button.textContent === '2014년~').click();
      return {chart: chart.map(button => button.textContent), credit: credit.map(button => button.textContent),
        defaultTab: document.querySelector('[role=tab][aria-selected=true]')?.textContent};
    })()`);
    assert.ok(state.chart.includes('2014년~')); assert.ok(!state.chart.includes('2013년~'));
    assert.ok(state.chart.includes('7일') && state.chart.includes('1년') && state.chart.includes('2년'));
    assert.ok(state.credit.includes('2014년~')); assert.ok(!state.credit.includes('2013년~'));
    assert.equal(state.defaultTab, '그리기·분석');
    await until(() => evaluate("document.querySelector('.stockHistoryChart .semiPanelHeading p')?.textContent.includes('2014년 1월 1일부터')"), 'Saved year identifier did not select its original date');
    const layout = await evaluate("({width: innerWidth, bodyWidth: document.documentElement.scrollWidth, activeCredit: document.querySelector('.creditPage .semiPeriodTabs .active')?.textContent, lines: document.querySelectorAll('.semiLine').length})");
    assert.equal(layout.activeCredit, '2014년~');
    assert.ok(layout.bodyWidth <= width, 'No horizontal overflow');
    assert.equal(await evaluate("[...document.querySelectorAll('.stockHistoryChart .semiFootnote')].some(el => el.textContent.includes('2025-11-18부터'))"), false);
    measurements.push({...layout, chartYears: state.chart.filter(label => label.includes('년~')).length});
    if (process.env.HISTORY_REVIEW_DIR && [1440, 390].includes(width)) {
      const shot = await send('Page.captureScreenshot', {format: 'png', captureBeyondViewport: false});
      await writeFile(join(process.env.HISTORY_REVIEW_DIR, `static-data-${width}.png`), Buffer.from(shot.data, 'base64'));
    }
  }
  const preserved = await evaluate("({price:document.querySelector('.stockHistoryChart .semiLine')?.getAttribute('d'),credit:document.querySelector('.creditHeadline strong')?.textContent,dates:[...document.querySelectorAll('.stockHistoryChart .semiFootnote')].at(-1)?.textContent})");
  await evaluate("document.querySelector('.stockHistoryChart .semiTextButton').click(); document.querySelector('.creditPage .refreshButton').click()");
  await until(() => evaluate("Boolean(document.querySelector('.stockHistoryChart .errorNotice') && document.querySelector('.creditPage .errorNotice'))"), 'Failed refresh did not surface');
  const retained = await evaluate("({price:document.querySelector('.stockHistoryChart .semiLine')?.getAttribute('d'),credit:document.querySelector('.creditHeadline strong')?.textContent,dates:[...document.querySelectorAll('.stockHistoryChart .semiFootnote')].at(-1)?.textContent})");
  assert.deepEqual(retained, preserved, 'Failed refresh retains prices, dates and balances');
  assert.deepEqual(failures, []);
  assert.ok(fixture.requests.some(request => request.origin === base));
  assert.ok(fixture.requests.every(request => request.range === undefined));
  assert.ok(fixture.requests.some(request => request.path.startsWith('blobs/')));
  const report = {result: 'PASS', fixture: true, staticResult, failed_refresh_retained: true, networkRequests: fixture.requests.length, measurements};
  console.log(JSON.stringify(report).replace(/[\u007f-\uffff]/g, character => '\\u' + character.charCodeAt(0).toString(16).padStart(4,'0')));
} finally {
  if (send && socket?.readyState === WebSocket.OPEN) await send('Browser.close').catch(() => {});
  socket?.close(); browser.kill(); await vite.close(); await fixture.close();
  assert.ok(resolve(profile).startsWith(resolve(tmpdir()) + sep));
  await rm(profile, {recursive: true, force: true, maxRetries: 10, retryDelay: 100});
}
