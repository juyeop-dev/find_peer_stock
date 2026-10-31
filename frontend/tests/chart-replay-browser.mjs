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
  const click = text => evaluate(`(()=>{const b=[...document.querySelectorAll('.chartReplayWorkspace button')].find(b=>b.textContent.trim()===${JSON.stringify(text)});if(!b)throw new Error('Missing button');b.click();})()`);
  const count = () => evaluate('Number(document.querySelector("[data-replay-count]").dataset.replayCount)');
  const setInput = (label, value) => evaluate(`(()=>{const n=document.querySelector('[aria-label='+${JSON.stringify(JSON.stringify(label))}+']');Object.getOwnPropertyDescriptor(n.tagName==='SELECT'?HTMLSelectElement.prototype:HTMLInputElement.prototype,'value').set.call(n,${JSON.stringify(value)});n.dispatchEvent(new Event(n.tagName==='SELECT'?'change':'input',{bubbles:true}));})()`);
  const ready = () => until(() => evaluate('Number(document.querySelector("[data-replay-max]")?.dataset.replayMax)>200'), 'Real market histories did not load');
  await send('Runtime.enable'); await send('Page.enable');
  await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1100, deviceScaleFactor: 1, mobile: false });
  await send('Page.navigate', { url: `${base}/charts` }); await ready();
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
  await click('설정 저장'); await send('Page.reload', { ignoreCache: true }); await ready();
  assert.equal(await count(), 40, 'Replay position was not restored');
  assert.equal(await evaluate(`document.querySelector('[aria-label="리플레이 봉 간격"]').value`), 'week');
  await click('크게 보기'); assert.equal(await evaluate('document.querySelector(".chartReplayWorkspace").getAttribute("aria-modal")'), 'true');
  await send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Escape', code: 'Escape' }); await send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Escape', code: 'Escape' });
  assert.equal(await evaluate('document.querySelector(".chartReplayWorkspace").hasAttribute("aria-modal")'), false);
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
  await click('재생'); await until(async () => await count() === 6, 'Playback did not reach shorter history end');
  await until(() => evaluate('document.querySelector(".replayPlay").getAttribute("aria-pressed")==="false"'), 'Playback did not stop automatically');
  assert.deepEqual(await evaluate('[...document.querySelectorAll("[data-visible-bars]")].map(n=>Number(n.dataset.visibleBars))'), [6, 6]);
  await click('예시: 코스피 2022 ↔ 금 2024');
  await setInput('리플레이 봉 간격', 'day'); await setInput('리플레이 위치', '80');
  const artifact = new URL('../../data/tmp_chart_replay/ui/', import.meta.url); await mkdir(artifact, { recursive: true });
  await rm(new URL('stock-peer-replay.png', artifact), { force: true });
  await send('Page.setDownloadBehavior', { behavior: 'allow', downloadPath: fileURLToPath(artifact) });
  await click('차트 이미지 저장');
  await until(() => existsSync(new URL('stock-peer-replay.png', artifact)), 'Chart PNG was not downloaded');
  assert.equal((await readFile(new URL('stock-peer-replay.png', artifact))).subarray(1, 4).toString(), 'PNG');
  for (const width of [1440, 390, 320]) {
    await send('Emulation.setDeviceMetricsOverride', { width, height: 1100, deviceScaleFactor: 1, mobile: false }); await delay(150);
    assert.equal(await evaluate('document.documentElement.scrollWidth>document.documentElement.clientWidth'), false, `Layout overflow at ${width}`);
    await evaluate('document.querySelector(".chartReplayWorkspace").scrollIntoView({block:"start"})');
    const shot = await send('Page.captureScreenshot', { format: 'png' }); await writeFile(new URL(`replay-${width}.png`, artifact), Buffer.from(shot.data, 'base64'));
  }
  await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1100, deviceScaleFactor: 1, mobile: false });
  await send('Page.navigate', { url: `${base}/semiconductors/000660.KS` }); await ready();
  assert.equal(await evaluate(`document.querySelector('[data-chart-view="workspace"]').getAttribute('aria-selected')`), 'true');
  assert.equal(await evaluate(`document.querySelector('[aria-label="차트 A 종목"]').value`), '000660.KS');
  assert.equal(await evaluate(`document.querySelector('[aria-label="리플레이 차트 종류"] option[value="candles"]').disabled`), true, 'Close-only archives cannot fabricate candles');
  await click('다음 봉'); const retained = await count();
  await click('재생');
  await evaluate(`document.querySelector('[data-chart-view="archive"]').click()`);
  await until(() => evaluate('document.querySelector(".stockChartCanvas")?.getBoundingClientRect().width>0'), 'Existing drawing chart is unavailable');
  assert.equal(await evaluate('document.querySelector(".replayPlay").getAttribute("aria-pressed")'), 'false', 'Hidden replay must pause');
  await evaluate(`document.querySelector('[data-chart-view="workspace"]').click()`);
  assert.equal(await count(), retained, 'Tab switches must preserve unsaved replay position');
  assert.equal(await evaluate('document.querySelectorAll(".marketWidget-chart iframe").length'), 0, 'Default stock chart must render in our site');
  assert.deepEqual(exceptions, [], 'Browser runtime errors');
  console.log('PASS real market replay, step/seek/speed, stop/restart, shorter history, candles, weekly aggregation, overlay, save/restore, fullscreen, PNG, invalid dates, 1440/390/320px layouts and native stock tabs with preserved drawing tools');
} finally {
  if (socket?.readyState === WebSocket.OPEN) socket.close();
  browser.kill(); await delay(500);
  const target = resolve(profile), temp = resolve(tmpdir()) + sep;
  if (!target.startsWith(temp) || !target.includes('chart-replay-')) throw new Error('Unexpected browser profile path');
  await rm(target, { recursive: true, force: true, maxRetries: 3, retryDelay: 200 });
}
