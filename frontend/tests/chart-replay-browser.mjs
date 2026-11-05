import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import { mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const base = process.env.STOCK_SITE_BASE_URL ?? 'http://127.0.0.1:4196';
const executable = ['C:/Program Files/Google/Chrome/Application/chrome.exe', 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', '/usr/bin/google-chrome', '/usr/bin/chromium'].find(existsSync);
assert.ok(executable, 'A browser is required');
const profile = await mkdtemp(join(tmpdir(), 'chart-replay-'));
const browser = spawn(executable, ['--headless=new', '--disable-gpu', '--no-sandbox', '--no-first-run', '--remote-debugging-port=0', `--user-data-dir=${profile}`, 'about:blank'], { windowsHide: true, stdio: 'ignore' });
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
async function until(check, message) { const end = Date.now() + 30000; while (Date.now() < end) { if (await check()) return; await delay(100); } throw new Error(message); }
let socket;
try {
  await until(() => existsSync(join(profile, 'DevToolsActivePort')), 'Browser did not launch');
  const [port] = (await readFile(join(profile, 'DevToolsActivePort'), 'utf8')).split(/\r?\n/);
  const pages = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  socket = new WebSocket(pages.find(p => p.type === 'page').webSocketDebuggerUrl);
  await new Promise(resolve => socket.addEventListener('open', resolve, { once: true }));
  let sequence = 0; const pending = new Map(), exceptions = [];
  socket.addEventListener('message', event => {
    const value = JSON.parse(event.data);
    if (value.method === 'Runtime.exceptionThrown') exceptions.push(value.params.exceptionDetails);
    const task = pending.get(value.id); if (!task) return; pending.delete(value.id); clearTimeout(task.timer);
    value.error ? task.reject(new Error(value.error.message)) : task.resolve(value.result);
  });
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const id = ++sequence, timer = setTimeout(() => { pending.delete(id); reject(new Error(`${method} timeout`)); }, 15000);
    pending.set(id, { resolve, reject, timer }); socket.send(JSON.stringify({ id, method, params }));
  });
  const evaluate = async expression => { const result = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true }); if (result.exceptionDetails) throw new Error(JSON.stringify(result.exceptionDetails)); return result.result.value; };
  const loadPage = async (method, params) => {
    const loaded = new Promise((resolve, reject) => {
      const listener = event => { if (JSON.parse(event.data).method === 'Page.loadEventFired') { clearTimeout(timer); socket.removeEventListener('message', listener); resolve(); } };
      const timer = setTimeout(() => { socket.removeEventListener('message', listener); reject(new Error('Page load timeout')); }, 30000);
      socket.addEventListener('message', listener);
    });
    await send(method, params); await loaded;
  };
  const click = text => evaluate(`(()=>{const b=[...document.querySelectorAll('.chartReplayWorkspace button')].find(b=>b.textContent.trim()===${JSON.stringify(text)});if(!b)throw new Error('Missing button');b.click();})()`);
  const count = () => evaluate('Number(document.querySelector("[data-replay-count]").dataset.replayCount)');
  const setInput = (label, value) => evaluate(`(()=>{const n=document.querySelector('[aria-label='+${JSON.stringify(JSON.stringify(label))}+']');Object.getOwnPropertyDescriptor(n.tagName==='SELECT'?HTMLSelectElement.prototype:HTMLInputElement.prototype,'value').set.call(n,${JSON.stringify(value)});n.dispatchEvent(new Event(n.tagName==='SELECT'?'change':'input',{bubbles:true}));})()`);
  const ready = () => until(() => evaluate('Number(document.querySelector("[data-replay-max]")?.dataset.replayMax)>200'), 'Real market histories did not load');
  await send('Runtime.enable'); await send('Page.enable');
  await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1100, deviceScaleFactor: 1, mobile: false });
  await loadPage('Page.navigate', { url: `${base}/charts` }); await ready();
  assert.equal(await count(), 25);
  assert.equal(await evaluate('document.querySelectorAll(".replayCanvas").length'), 2);
  assert.ok(await evaluate('document.querySelectorAll(".replayCanvas canvas").length') >= 4);
  const dates = await evaluate('[...document.querySelectorAll("[data-visible-date]")].map(n=>n.dataset.visibleDate)');
  assert.ok(dates[0].startsWith('2022-')); assert.ok(dates[1].startsWith('2024-'));
  assert.equal(await evaluate('document.querySelectorAll(".chartReplayWorkspace iframe").length'), 0);
  await click('다음 봉'); assert.equal(await count(), 26);
  await click('이전 봉'); assert.equal(await count(), 25);
  await click('↤ 처음'); assert.equal(await count(), 1);
  await setInput('리플레이 속도', '10'); await click('재생');
  await until(async () => await count() >= 4, 'Playback did not advance');
  await click('일시정지'); const paused = await count(); await delay(250); assert.equal(await count(), paused);
  await setInput('리플레이 위치', '40'); assert.equal(await count(), 40);
  await setInput('리플레이 차트 종류', 'candles');
  await setInput('리플레이 봉 간격', 'week');
  await evaluate('document.querySelector(".replayToolbar input").click()');
  await click('수익률 겹쳐 보기');
  await until(() => evaluate('document.querySelectorAll(".replayCanvas").length===1'), 'Overlay did not render');
  assert.equal(await evaluate(`document.querySelector('[aria-label="리플레이 봉 간격"]').disabled`), true);
  await click('나란히 보기');
  await click('설정 저장'); await loadPage('Page.reload', { ignoreCache: true }); await ready();
  assert.equal(await count(), 40, 'Replay position was not restored');
  assert.equal(await evaluate(`document.querySelector('[aria-label="리플레이 봉 간격"]').value`), 'week');
  await click('크게 보기'); assert.equal(await evaluate('document.querySelector(".chartReplayWorkspace").getAttribute("aria-modal")'), 'true');
  await send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Escape', code: 'Escape' }); await send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Escape', code: 'Escape' });
  assert.equal(await evaluate('document.querySelector(".chartReplayWorkspace").hasAttribute("aria-modal")'), false);
  const applySelection = index => evaluate(`document.querySelectorAll('.replaySelection')[${index}].querySelector('button[type="submit"]').click()`);
  const fullyVisible = async () => {
    await ready();
    await until(() => evaluate('Number(document.querySelector("[data-replay-count]").dataset.replayCount)===Number(document.querySelector("[data-replay-max]").dataset.replayMax)'), 'Applying a selection collapsed the chart to the first sessions');
    const maximum = await evaluate('Number(document.querySelector("[data-replay-max]").dataset.replayMax)');
    assert.deepEqual(await evaluate('[...document.querySelectorAll("[data-visible-bars]")].map(n=>Number(n.dataset.visibleBars))'), [maximum, maximum]);
    assert.equal(await evaluate('document.querySelectorAll(".replaySelectionError").length'), 0);
  };
  // The short built-in name must work even before the stock catalog loads.
  await setInput('차트 B 종목', '금'); await applySelection(1); await fullyVisible();
  assert.equal(await evaluate('document.querySelectorAll(".replayReadout > div:first-child span")[1].textContent'), 'GC=F');
  // Hold the catalog request: an immediate name submission must wait for it.
  let catalogRequest;
  socket.addEventListener('message', event => { const value = JSON.parse(event.data); if (value.method === 'Fetch.requestPaused') catalogRequest = value.params.requestId; });
  await send('Fetch.enable', { patterns: [{ urlPattern: '*data/chart-catalog.json.gz*', requestStage: 'Request' }] });
  await evaluate(`document.querySelector('[aria-label="차트 B 종목"]').focus()`);
  await until(() => catalogRequest, 'Stock catalog request did not start');
  await setInput('차트 B 종목', 'SK하이닉스'); await applySelection(1);
  assert.equal(await evaluate('document.querySelectorAll(".replaySelection")[1].querySelector("button[type=submit]").disabled'), true);
  await send('Fetch.continueRequest', { requestId: catalogRequest }); await send('Fetch.disable');
  await until(() => evaluate('document.querySelectorAll(".replayReadout > div:first-child span")[1].textContent==="000660.KS"'), 'B Korean name was not resolved after catalog load');
  await fullyVisible();
  // Real IME typing produces clickable Korean results for A as well.
  await evaluate(`(()=>{const input=document.querySelector('[aria-label="차트 A 종목"]');input.focus();input.select();})()`);
  await send('Input.imeSetComposition', { text: '삼성', selectionStart: 2, selectionEnd: 2 });
  await send('Input.insertText', { text: '삼성' });
  await until(() => evaluate('[...document.querySelectorAll(".replaySearchResults button")].some(n=>n.textContent.includes("005930.KS"))'), 'Korean results are missing');
  await evaluate('[...document.querySelectorAll(".replaySearchResults button")].find(n=>n.textContent.includes("005930.KS")).click()');
  await applySelection(0);
  await until(() => evaluate('document.querySelectorAll(".replayReadout > div:first-child span")[0].textContent==="005930.KS"'), 'A search result did not apply');
  await fullyVisible();
  const artifact = new URL('../../data/tmp_chart_replay/ui/', import.meta.url); await mkdir(artifact, { recursive: true });
  await evaluate('document.querySelector(".chartReplayWorkspace").scrollIntoView({block:"start"})');
  await delay(150);
  const updated = await send('Page.captureScreenshot', { format: 'png' });
  await writeFile(new URL('replay-updated-full-period.png', artifact), Buffer.from(updated.data, 'base64'));
  // Keyboard selection and lowercase direct tickers preserve the same window.
  await evaluate(`document.querySelector('[aria-label="차트 B 종목"]').focus()`);
  await setInput('차트 B 종목', '코스피');
  await send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Enter', code: 'Enter' });
  await send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Enter', code: 'Enter' });
  await until(() => evaluate(`document.querySelector('[aria-label="차트 B 종목"]').value==='^KS11'`), 'Keyboard selection failed');
  await applySelection(1); await fullyVisible();
  await setInput('차트 B 종목', '000660.ks'); await applySelection(1);
  await until(() => evaluate('document.querySelectorAll(".replayReadout > div:first-child span")[1].textContent==="000660.KS"'), 'Direct ticker failed');
  await fullyVisible();
  await setInput('차트 B 종목', '없는종목이름'); await applySelection(1);
  await until(() => evaluate('document.querySelectorAll(".replaySelection")[1].querySelector(".replaySelectionError")?.textContent.includes("올바른 티커")'), 'Unknown name was not rejected');
  await setInput('차트 B 종목', '삼성'); await applySelection(1);
  await until(() => evaluate('Boolean(document.querySelectorAll(".replaySelection")[1].querySelector(".replaySelectionError"))'), 'Ambiguous name must require a result selection');
  assert.equal(await evaluate('document.querySelectorAll(".replayReadout > div:first-child span")[1].textContent'), '000660.KS', 'Invalid or ambiguous names must preserve B');
  // Restore known periods before the transport and date validation checks.
  await click('예시: 코스피 2022 ↔ 금 2024'); await ready();
  // Invalid dates must leave the applied selection intact.
  await setInput('차트 A 시작일', '2025-01-01');
  await evaluate('document.querySelector(".replaySelection button").click()');
  assert.ok(await evaluate('document.querySelector(".replaySelectionError")?.textContent.includes("날짜")'));
  await click('예시: 코스피 2022 ↔ 금 2024'); await ready();
  await click('끝으로');
  assert.equal(await count(), await evaluate('Number(document.querySelector("[data-replay-max]").dataset.replayMax)'));
  await click('재생'); await until(async () => await count() < 10, 'Play at end did not restart'); await click('일시정지');
  // A shorter, valid history stops both panels at the shorter series.
  await setInput('차트 A 시작일', '2022-01-03'); await setInput('차트 A 종료일', '2022-01-10');
  await evaluate('document.querySelector(".replaySelection button").click()');
  await until(() => evaluate('Number(document.querySelector("[data-replay-max]").dataset.replayMax)===6'), 'Short history was not applied');
  assert.equal(await count(), 6, 'A short applied range should also open fully');
  await click('재생'); await until(async () => await count() === 6, 'Playback did not reach shorter history end');
  await until(() => evaluate('document.querySelector(".replayPlay").getAttribute("aria-pressed")==="false"'), 'Playback did not stop automatically');
  assert.deepEqual(await evaluate('[...document.querySelectorAll("[data-visible-bars]")].map(n=>Number(n.dataset.visibleBars))'), [6, 6]);
  await click('예시: 코스피 2022 ↔ 금 2024');
  await setInput('리플레이 봉 간격', 'day'); await setInput('리플레이 위치', '80');
  await rm(new URL('stock-peer-replay.png', artifact), { force: true });
  await send('Page.setDownloadBehavior', { behavior: 'allow', downloadPath: fileURLToPath(artifact) });
  await click('차트 이미지 저장');
  await until(() => existsSync(new URL('stock-peer-replay.png', artifact)), 'Chart PNG was not downloaded');
  assert.equal((await readFile(new URL('stock-peer-replay.png', artifact))).subarray(1, 4).toString(), 'PNG');
  for (const width of [1440, 390, 320]) {
    await send('Emulation.setDeviceMetricsOverride', { width, height: 1100, deviceScaleFactor: 1, mobile: false }); await delay(150);
    await evaluate(`document.querySelector('[aria-label="차트 B 종목"]').focus()`);
    await setInput('차트 B 종목', '삼성');
    await until(() => evaluate('document.querySelectorAll(".replaySearchResults button").length>0'), 'Search results did not open');
    assert.equal(await evaluate('document.documentElement.scrollWidth>document.documentElement.clientWidth'), false, `Layout overflow at ${width}`);
    await evaluate('document.activeElement.blur()');
    await evaluate('document.querySelector(".chartReplayWorkspace").scrollIntoView({block:"start"})');
    const shot = await send('Page.captureScreenshot', { format: 'png' }); await writeFile(new URL(`replay-${width}.png`, artifact), Buffer.from(shot.data, 'base64'));
  }
  await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1100, deviceScaleFactor: 1, mobile: false });
  await loadPage('Page.navigate', { url: `${base}/semiconductors/000660.KS` });
  await until(() => evaluate('Boolean(document.querySelector("[data-chart-view=archive]"))'), 'Stock chart tabs are missing');
  assert.equal(await evaluate(`document.querySelector('[data-chart-view="archive"]').getAttribute('aria-selected')`), 'true');
  assert.equal(await evaluate('document.querySelectorAll(".chartReplayWorkspace").length'), 0, 'Replay must load only when opened');
  await evaluate(`document.querySelector('[data-chart-view="workspace"]').click()`); await ready();
  assert.equal(await evaluate('document.querySelectorAll(".replayCanvas").length'), 1, 'Stock replay must default to return overlay');
  assert.notEqual(await evaluate(`document.querySelector('[aria-label="차트 B 종목"]').value`), 'GC=F');
  assert.ok(await evaluate('Boolean(document.querySelector("[data-peer-reason]").textContent.includes("선정"))'));
  assert.equal(await evaluate(`document.querySelector('[aria-label="차트 A 종목"]').value`), '000660.KS');
  assert.equal(await evaluate(`document.querySelector('[aria-label="리플레이 차트 종류"] option[value="candles"]').disabled`), true, 'Close-only archives cannot fabricate candles');
  await click('↤ 처음'); await click('다음 봉'); const retained = await count();
  await click('재생');
  await evaluate(`document.querySelector('[data-chart-view="archive"]').click()`);
  await until(() => evaluate('document.querySelector(".stockChartCanvas")?.getBoundingClientRect().width>0'), 'Existing drawing chart is unavailable');
  assert.equal(await evaluate('document.querySelector(".replayPlay").getAttribute("aria-pressed")'), 'false', 'Hidden replay must pause');
  await evaluate(`document.querySelector('[data-chart-view="workspace"]').click()`);
  assert.equal(await count(), retained, 'Tab switches must preserve unsaved replay position');
  assert.equal(await evaluate('document.querySelectorAll(".marketWidget-chart iframe").length'), 0, 'Default stock chart must render in our site');
  const assertAnalysisFirst = async route => {
    await loadPage('Page.navigate', { url: base + route });
    await until(() => evaluate('Boolean(document.querySelector("[data-chart-view=archive]"))'), 'Analysis tab missing');
    assert.equal(await evaluate('document.querySelector("[data-chart-view=archive]").getAttribute("aria-selected")'), 'true');
    assert.equal(await evaluate('document.querySelectorAll(".chartReplayWorkspace").length'), 0);
    await evaluate('document.querySelector("[data-chart-view=workspace]").click()'); await ready();
    assert.equal(await evaluate('document.querySelectorAll(".replayCanvas").length'), 1);
  };
  await assertAnalysisFirst('/stocks/MU');
  const muPeer = await evaluate(`document.querySelector('[aria-label="차트 B 종목"]').value`);
  assert.ok(['005930.KS', '000660.KS', '2408.TW', '2344.TW'].includes(muPeer), 'Micron should compare against a memory-business peer');
  assert.deepEqual(await evaluate('[...document.querySelectorAll(".replaySelection input[type=date]")].map(n=>n.value)'),
    await evaluate('(()=>{const n=document.querySelectorAll(".replaySelection input[type=date]");return[n[0].value,n[1].value,n[0].value,n[1].value]})()'));
  const latestRebounds = await (await fetch(base + '/data/rebounds/index.json')).json();
  const reboundDate = latestRebounds.reports.find(row => row.count > 0).date;
  const reboundReport = await (await fetch(`${base}/data/rebounds/korea/${reboundDate.slice(0,7).replace('-','_')}/${reboundDate}.json`)).json();
  await assertAnalysisFirst(`/market-stocks/${encodeURIComponent(reboundReport.entries[0].ticker)}?source=rebounds&market=korea&date=${reboundDate}`);
  // Legacy automatic gold defaults migrate, while an explicitly saved peer survives.
  const legacy = { version: 1, overlay: false, count: 25, selections: [
    { ticker: 'MU', name: 'Micron', exchange: 'NASDAQ', start: '2025-01-01', end: '2026-12-31' },
    { ticker: 'GC=F', name: 'Gold', start: '2024-01-01', end: '2024-12-31' },
  ] };
  await evaluate(`localStorage.setItem('stock-peer:replay:v1:MU',${JSON.stringify(JSON.stringify(legacy))})`);
  await assertAnalysisFirst('/stocks/MU');
  assert.notEqual(await evaluate(`document.querySelector('[aria-label="차트 B 종목"]').value`), 'GC=F');
  assert.equal(await count(), await evaluate('Number(document.querySelector("[data-replay-max]").dataset.replayMax)'));
  const manual = { ...legacy, count: 40, selections: [legacy.selections[0], { ...legacy.selections[0], ticker: '000660.KS', name: 'SK하이닉스', exchange: 'KOSPI' }] };
  await evaluate(`localStorage.setItem('stock-peer:replay:v1:MU',${JSON.stringify(JSON.stringify(manual))})`);
  await assertAnalysisFirst('/stocks/MU');
  assert.equal(await evaluate(`document.querySelector('[aria-label="차트 B 종목"]').value`), '000660.KS');
  assert.equal(await count(), 40);
  // A delayed automatic suggestion must never overwrite a manual selection.
  let peerCatalogRequest;
  const holdPeerCatalog = event => { const message = JSON.parse(event.data); if (message.method === 'Fetch.requestPaused') peerCatalogRequest = message.params.requestId; };
  socket.addEventListener('message', holdPeerCatalog);
  await send('Fetch.enable', { patterns: [{ urlPattern: '*data/chart-catalog.json.gz*', requestStage: 'Request' }] });
  await loadPage('Page.navigate', { url: `${base}/semiconductors/005930.KS` });
  await until(() => evaluate('Boolean(document.querySelector("[data-chart-view=archive]"))'), 'Samsung analysis tab missing');
  assert.equal(peerCatalogRequest, undefined, 'Hidden replay must not start the catalog request');
  await evaluate('document.querySelector("[data-chart-view=workspace]").click()');
  await until(() => peerCatalogRequest, 'Automatic peer lookup did not start');
  await setInput('차트 B 종목', 'MU'); await applySelection(1); await ready();
  await send('Fetch.continueRequest', { requestId: peerCatalogRequest }); await send('Fetch.disable');
  socket.removeEventListener('message', holdPeerCatalog);
  await delay(250);
  assert.equal(await evaluate(`document.querySelector('[aria-label="차트 B 종목"]').value`), 'MU');
  assert.deepEqual(exceptions, [], 'Browser runtime errors');
  console.log('PASS Korean search/IME, replay/aggregation/overlay/save/PNG, 1440/390/320px, analysis-first tabs on all three detail types, same-period business peers, legacy default migration, manual saved peers and delayed automatic suggestions preserving manual choices');
} finally {
  if (socket?.readyState === WebSocket.OPEN) socket.close();
  browser.kill(); await delay(500);
  const target = resolve(profile), temp = resolve(tmpdir()) + sep;
  if (!target.startsWith(temp) || !target.includes('chart-replay-')) throw new Error('Unexpected browser profile path');
  await rm(target, { recursive: true, force: true, maxRetries: 3, retryDelay: 200 });
}
