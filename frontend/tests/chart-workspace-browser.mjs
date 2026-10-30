import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {existsSync} from 'node:fs';
import {mkdir,mkdtemp,readFile,rm,writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join,resolve,sep} from 'node:path';
const base=process.env.STOCK_SITE_BASE_URL??'http://127.0.0.1:4192/find_peer_stock';
const executable=['C:/Program Files/Google/Chrome/Application/chrome.exe','C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe','/usr/bin/google-chrome','/usr/bin/chromium'].find(existsSync);assert.ok(executable);
const profile=await mkdtemp(join(tmpdir(),'chart-workspace-'));
const browser=spawn(executable,['--headless=new','--disable-gpu','--no-sandbox','--no-first-run','--remote-debugging-port=0',`--user-data-dir=${profile}`,'about:blank'],{windowsHide:true,stdio:'ignore'});
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function until(check,message) {const end=Date.now()+90000;while(Date.now()<end){if(await check())return;await delay(100);}throw new Error(message);}
let socket,send;
try {
  await until(()=>existsSync(join(profile,'DevToolsActivePort')),'Browser did not launch');
  const [port]=(await readFile(join(profile,'DevToolsActivePort'),'utf8')).split(/\r?\n/);
  const pages=await(await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  socket=new WebSocket(pages.find(p=>p.type==='page').webSocketDebuggerUrl);
  await new Promise(resolve=>socket.addEventListener('open',resolve,{once:true}));
  let sequence=0;const pending=new Map(),exceptions=[];
  socket.addEventListener('message',event=>{
    const value=JSON.parse(event.data);
    if(value.method==='Runtime.exceptionThrown')exceptions.push(value.params.exceptionDetails);
    const task=pending.get(value.id);if(!task)return;pending.delete(value.id);clearTimeout(task.timer);
    value.error?task.reject(new Error(value.error.message)):task.resolve(value.result);
  });
  send=(method,params={})=>new Promise((resolve,reject)=>{
    const id=++sequence,timer=setTimeout(()=>{pending.delete(id);reject(new Error(method+' timeout'));},15000);
    pending.set(id,{resolve,reject,timer});socket.send(JSON.stringify({id,method,params}));
  });
  const evaluate=async expression=>{const result=await send('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(result.exceptionDetails)throw new Error(JSON.stringify(result.exceptionDetails));return result.result.value;};
  const clickText=(text,scope='.stockChartWorkspace')=>evaluate(`(()=>{const button=[...document.querySelectorAll(${JSON.stringify(scope)}+' button')].find(node=>node.textContent.trim()===${JSON.stringify(text)} || node.textContent.replace(node.querySelector('span')?.textContent??'','').trim()===${JSON.stringify(text)});if(!button)throw new Error('Missing button: '+${JSON.stringify(text)});button.click();})()`);
  const navigate=route=>send('Page.navigate',{url:base+route});
  const chartReady=()=>until(()=>evaluate("Boolean(document.querySelector('.stockChartCanvas .semiLine')?.getAttribute('d'))"),'Stock chart did not render');
  const drawingCount=()=>evaluate("document.querySelectorAll('.chartDrawing:not([data-drawing=draft])').length");
  const mouse=async(type,point,buttons=0)=>send('Input.dispatchMouseEvent',{type,x:point.x,y:point.y,...(type==='mouseMoved'?{buttons}:{button:'left',clickCount:1,buttons})});
  const tap=async point=>{await mouse('mouseMoved',point);await mouse('mousePressed',point,1);await mouse('mouseReleased',point);};
  const plotPoint=async(fx,fy)=>evaluate(`(()=>{const svg=document.querySelector('.stockChartCanvas svg');svg.scrollIntoView({block:'center'});const w=svg.viewBox.baseVal.width,left=w<480?66:84,bottom=w<480?272:302;const point=new DOMPoint(left+(w-22-left)*${fx},22+(bottom-22)*${fy}).matrixTransform(svg.getScreenCTM());return{x:point.x,y:point.y};})()`);
  const search=async query=>{
    await evaluate(`(()=>{const input=document.querySelector('.chartSymbolSearch input');input.focus();Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,${JSON.stringify(query)});input.dispatchEvent(new Event('input',{bubbles:true}));})()`);
    await delay(500);
    console.log(await evaluate("JSON.stringify({search:document.querySelector('.chartSymbolSearch input')?.value,catalogError:document.querySelector('.chartStatus')?.innerText,options:document.querySelectorAll('.chartSearchResults button').length})"));
    await until(()=>evaluate("document.querySelectorAll('.chartSearchResults button').length>0"),'Comparison search returned no options: '+query);
  };
  const add=async(ticker,query=ticker)=>{
    await search(query);
    await until(()=>evaluate(`Boolean([...document.querySelectorAll('.chartSearchResults button')].find(node=>node.textContent.includes(${JSON.stringify(ticker)})))`),'Missing comparison result '+ticker);
    await evaluate(`[...document.querySelectorAll('.chartSearchResults button')].find(node=>node.textContent.includes(${JSON.stringify(ticker)})).click()`);
  };
  await send('Runtime.enable');await send('Network.enable');
  await send('Emulation.setDeviceMetricsOverride',{width:1440,height:1100,deviceScaleFactor:1,mobile:false});
  await navigate('/semiconductors/000660.KS');await chartReady();
  await clickText('추세선');await tap(await plotPoint(.2,.7));await tap(await plotPoint(.8,.3));
  await until(async()=>await drawingCount()===1,'Two-click trend line was not drawn');
  await clickText('수평선');await tap(await plotPoint(.5,.65));
  await clickText('수직선');await tap(await plotPoint(.4,.4));
  assert.equal(await drawingCount(),3);
  await clickText('이동');
  const oldRange=await evaluate("document.querySelector('.chartRangeControls').innerText");
  await clickText('＋ 확대');
  await until(()=>evaluate(`document.querySelector('.chartRangeControls').innerText!==${JSON.stringify(oldRange)}`),'Zoom did not change the visible session count');
  const zoomed=await evaluate("document.querySelector('.chartRangeControls input').value");
  const panStart=await plotPoint(.65,.2),panEnd=await plotPoint(.3,.2);
  await mouse('mousePressed',panStart,1);await mouse('mouseMoved',panEnd,1);await mouse('mouseReleased',panEnd);
  assert.notEqual(await evaluate("document.querySelector('.chartRangeControls input').value"),zoomed,'Drag did not pan the zoomed timeline');
  await clickText('범위 초기화');
  const linePosition=await evaluate("(()=>{const line=document.querySelectorAll('.chartDrawingHit')[1],svg=line.ownerSVGElement;const point=new DOMPoint((+line.getAttribute('x1') + +line.getAttribute('x2'))/2,+line.getAttribute('y1')).matrixTransform(svg.getScreenCTM());return{x:point.x,y:point.y};})()");
  await tap(linePosition);
  await until(()=>evaluate("Boolean(document.querySelector('.chartDrawingHandle'))"),'Drawing could not be selected');
  const oldY=await evaluate("document.querySelector('.chartDrawing.selected line').getAttribute('y1')");
  const handle=await evaluate("(()=>{const node=document.querySelector('.chartDrawingHandle'),p=new DOMPoint(+node.getAttribute('cx'),+node.getAttribute('cy')).matrixTransform(node.ownerSVGElement.getScreenCTM());return{x:p.x,y:p.y};})()");
  await mouse('mousePressed',handle,1);await mouse('mouseMoved',{x:handle.x,y:handle.y-25},1);await mouse('mouseReleased',{x:handle.x,y:handle.y-25});
  assert.notEqual(await evaluate("document.querySelector('.chartDrawing.selected line').getAttribute('y1')"),oldY,'Dragging a handle did not edit the saved line');
  await clickText('선택 삭제');assert.equal(await drawingCount(),2);
  await clickText('실행 취소');assert.equal(await drawingCount(),3);
  console.log('PASS drawing creation, selection, editing, deletion, undo and zoom/pan');
  await clickText('선 모두 지우기');assert.equal(await drawingCount(),0);
  await clickText('실행 취소');assert.equal(await drawingCount(),3);
  await evaluate("document.querySelector('.chartIndicators input').click()");
  await until(()=>evaluate("document.querySelectorAll('.chartAverageLine').length===1"),'Moving average did not render');
  await clickText('2019년~','.stockHistoryChart .semiPeriodTabs');await chartReady();assert.equal(await drawingCount(),3);
  assert.ok((await evaluate("document.querySelector('.stockChartCanvas').getAttribute('aria-label')")).includes('2018-12'));
  await send('Page.reload',{ignoreCache:true});await chartReady();assert.equal(await drawingCount(),3,'Drawings were not restored after refresh');
  await navigate('/semiconductors/005930.KS');await chartReady();assert.equal(await drawingCount(),0,'Another ticker inherited drawings');
  await navigate('/semiconductors/000660.KS');await chartReady();assert.equal(await drawingCount(),3);
  console.log('PASS persistence, ticker isolation, moving average and 2019 range');
  await add('005930.KS','삼성전자');
  await until(()=>evaluate("document.querySelectorAll('.stockChartCanvas .semiLine').length===2"),'Comparison series failed to load');
  assert.ok((await evaluate("document.querySelector('.chartBasis').innerText")).includes('환율 미반영'));
  assert.ok(await evaluate("document.querySelector('.chartToolGroup[aria-label=\"차트 표시 단위\"] button').disabled"));
  const starts=await evaluate("[...document.querySelectorAll('.stockChartCanvas .semiLine')].map(node=>node.getAttribute('d').split(' ')[0])");
  assert.equal(starts[0],starts[1],'Comparison lines must begin at the same date and 0%');
  assert.equal(await drawingCount(),0,'Price drawings leaked into return coordinates');
  await add('AAPL');await until(()=>evaluate("document.querySelectorAll('.stockChartCanvas .semiLine').length===3"),'Cross-currency comparison failed to load');
  console.log('PASS Korean-name search and cross-currency common-date comparisons');
  for(const width of [1440,390,320]) {
    await send('Emulation.setDeviceMetricsOverride',{width,height:1100,deviceScaleFactor:1,mobile:false});await delay(150);
    assert.equal(await evaluate('document.documentElement.scrollWidth>innerWidth'),false,'Page overflows at '+width);
    await evaluate("document.querySelector('.stockChartWorkspace').scrollIntoView({block:'start'})");
    const shot=await send('Page.captureScreenshot',{format:'png'}),folder=new URL('../../data/tmp_chart_tools/ui/',import.meta.url);await mkdir(folder,{recursive:true});await writeFile(new URL(`chart-${width}.png`,folder),Buffer.from(shot.data,'base64'));
  }
  await clickText('크게 보기');assert.equal(await evaluate("document.querySelector('.stockChartWorkspace').getAttribute('aria-modal')"),'true');
  await send('Input.dispatchKeyEvent',{type:'keyDown',key:'Escape',code:'Escape'});await send('Input.dispatchKeyEvent',{type:'keyUp',key:'Escape',code:'Escape'});
  await until(()=>evaluate("!document.querySelector('.stockChartWorkspace').classList.contains('isExpanded')"),'Escape did not close expanded chart');
  await send('Emulation.setDeviceMetricsOverride',{width:1440,height:1100,deviceScaleFactor:1,mobile:false});
  await evaluate("document.querySelector('[aria-label=\"AAPL 비교 제거\"]').click()");
  // Simulate unavailable and non-overlapping listings at the browser network boundary.
  const fake={ticker:'TEST_OLD',currency:'USD',source:'browser-test fixture',fetched_at:new Date().toISOString(),prices:[['2010-01-04',10,10],['2010-01-05',11,11]]};
  socket.addEventListener('message',event=>{
    const message=JSON.parse(event.data);if(message.method!=='Fetch.requestPaused')return;
    const {requestId,request}=message.params;let ticker='';
    try{ticker=JSON.parse(request.postData??'{}').stocks?.[0]?.ticker??'';}catch{}
    if(request.url.includes('TEST_OLD')||ticker==='TEST_OLD') {
      const body=request.url.includes('/refresh')?{items:[{...fake,history:fake.prices.map(([date,close,adjusted_close])=>({date,close,adjusted_close,volume:null}))}],errors:[]}:fake;
      void send('Fetch.fulfillRequest',{requestId,responseCode:200,responseHeaders:[{name:'Content-Type',value:'application/json'},{name:'Access-Control-Allow-Origin',value:new URL(base).origin}],body:Buffer.from(JSON.stringify(body)).toString('base64')});
    } else if(request.url.includes('TEST_FAIL')||ticker==='TEST_FAIL') void send('Fetch.fulfillRequest',{requestId,responseCode:502,responseHeaders:[{name:'Content-Type',value:'application/json'},{name:'Access-Control-Allow-Origin',value:new URL(base).origin}],body:Buffer.from(JSON.stringify({error:'비교 종목 테스트 조회 실패'})).toString('base64')});
    else void send('Fetch.continueRequest',{requestId});
  });
  await send('Fetch.enable',{patterns:[{urlPattern:'*/data/stock-history/*',requestStage:'Request'},{urlPattern:'*/refresh',requestStage:'Request'}]});
  await add('TEST_OLD');await until(()=>evaluate("document.querySelector('.chartBasis').innerText.includes('공통 거래일이 2개')"),'No-overlap comparison did not disclose insufficient shared dates');
  assert.equal(await evaluate("document.querySelectorAll('.stockChartCanvas .semiLine').length"),0,'No-overlap comparison fabricated a curve');
  await evaluate("document.querySelector('[aria-label=\"TEST_OLD 비교 제거\"]').click()");await chartReady();
  await add('TEST_FAIL');await until(()=>evaluate("document.querySelector('.chartComparisonChips .hasError')?.innerText.includes('비교 종목 테스트 조회 실패')"),'Failed comparison was not disclosed');
  assert.equal(await evaluate("document.querySelectorAll('.stockChartCanvas .semiLine').length"),2,'Failed comparison erased existing curves');
  await evaluate("document.querySelector('[aria-label=\"TEST_FAIL 비교 제거\"]').click();document.querySelector('[aria-label=\"005930.KS 비교 제거\"]').click()");
  await clickText('가격');await chartReady();assert.equal(await drawingCount(),3,'Saved price drawings were not restored after comparison mode');
  await send('Emulation.setDeviceMetricsOverride',{width:390,height:1100,deviceScaleFactor:1,mobile:true});
  await send('Emulation.setTouchEmulationEnabled',{enabled:true,maxTouchPoints:1});
  await clickText('수평선');
  const touchPoint=await plotPoint(.5,.4);
  await send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{...touchPoint,radiusX:1,radiusY:1,force:1}]});
  await send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});
  await until(async()=>await drawingCount()===4,'Touch drawing did not create a horizontal line');
  await clickText('실행 취소');assert.equal(await drawingCount(),3);
  assert.deepEqual(exceptions,[]);
  console.log(JSON.stringify({result:'PASS',site:base,checks:'Real Korean-name and global ticker search; adjusted common-date cross-currency comparisons; missing overlap and provider failure; trend/horizontal/vertical drawing, endpoint editing, delete/undo/clear, per-ticker persistence and coordinate modes; zoom, drag pan, moving average, 2019 range, expanded view, touch drawing, 1440/390/320px'}));
} finally {
  if(send&&socket?.readyState===WebSocket.OPEN)await send('Browser.close').catch(()=>{});socket?.close();browser.kill();
  assert.ok(resolve(profile).startsWith(resolve(tmpdir())+sep));await rm(profile,{recursive:true,force:true,maxRetries:10,retryDelay:100});
}
