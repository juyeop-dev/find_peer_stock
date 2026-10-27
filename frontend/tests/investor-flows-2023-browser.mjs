import assert from "node:assert/strict";
import {spawn} from "node:child_process";
import {existsSync} from "node:fs";
import {mkdtemp,readFile,rm,mkdir,writeFile} from "node:fs/promises";
import {tmpdir} from "node:os";
import {join,resolve,sep} from "node:path";

const base=process.env.STOCK_SITE_BASE_URL??"http://127.0.0.1:4174";
const archive=await(await fetch(base+"/data/investors/index.json")).json();
const executable=["C:/Program Files/Google/Chrome/Application/chrome.exe","C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe","/usr/bin/chromium"].find(existsSync);assert.ok(executable);
const profile=await mkdtemp(join(tmpdir(),"investor-flows-"));
const browser=spawn(executable,["--headless=new","--disable-gpu","--no-sandbox","--no-first-run","--remote-debugging-port=0",`--user-data-dir=${profile}`,"about:blank"],{windowsHide:true,stdio:"ignore"});
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function until(check,message) {const deadline=Date.now()+90000;while(Date.now()<deadline){if(await check())return;await delay(100);}throw new Error(message);}
let socket,send;
try {
  await until(()=>existsSync(join(profile,"DevToolsActivePort")),"Browser unavailable");
  const [port]=(await readFile(join(profile,"DevToolsActivePort"),"utf8")).split(/\r?\n/),targets=await(await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  socket=new WebSocket(targets.find(value=>value.type==="page").webSocketDebuggerUrl);await new Promise(resolve=>socket.addEventListener("open",resolve,{once:true}));
  let sequence=0;const pending=new Map(),exceptions=[],requests=new Map(),responses=[];
  socket.addEventListener("message",event=>{
    const value=JSON.parse(event.data);
    if(value.method==="Runtime.exceptionThrown")exceptions.push(value.params.exceptionDetails);
    if(value.method==="Network.requestWillBeSent"&&value.params.request.postData){try{const body=JSON.parse(value.params.request.postData);if(body.kind==="investors")requests.set(value.params.requestId,body);}catch{}}
    if(value.method==="Network.responseReceived"&&requests.has(value.params.requestId))responses.push({...requests.get(value.params.requestId),status:value.params.response.status});
    const task=pending.get(value.id);if(!task)return;pending.delete(value.id);clearTimeout(task.timer);value.error?task.reject(new Error(value.error.message)):task.resolve(value.result);
  });
  send=(method,params={})=>new Promise((resolve,reject)=>{const id=++sequence,timer=setTimeout(()=>{pending.delete(id);reject(new Error(method+" timeout"));},15000);pending.set(id,{resolve,reject,timer});socket.send(JSON.stringify({id,method,params}));});
  const evaluate=async expression=>{const result=await send("Runtime.evaluate",{expression,returnByValue:true,awaitPromise:true});if(result.exceptionDetails)throw new Error(JSON.stringify(result.exceptionDetails));return result.result.value;};
  const navigate=route=>send("Page.navigate",{url:base+route});
  const click=selector=>evaluate(`document.querySelector(${JSON.stringify(selector)}).click()`);
  const verify=async(date,market="all")=>{
    const day=archive.history.find(row=>row.date===date);assert.ok(day);
    await until(()=>evaluate(`document.querySelector('.investorDateHeading h2')?.innerText.includes('${date}') && document.querySelectorAll('.investorFlowTable tbody tr').length===${market==="all"?8:4}`),"Selected flow day/market did not load");
    const shown=await evaluate("[...document.querySelectorAll('.investorFlowTable tbody tr')].map(row=>({market:row.dataset.market,key:row.dataset.investor,values:[...row.children].slice(2,5).map(node=>Number(node.innerText.replaceAll(',','')))}))");
    for(const row of shown) {const expected=day.markets.find(value=>value.market===row.market).investors.find(value=>value.key===row.key);assert.deepEqual(row.values,[expected.buy,expected.sell,expected.net].map(value=>Number((value/1e8).toFixed(2))));}
    const indices=await evaluate("[...document.querySelectorAll('.investorIndices > button')].map(row=>({date:row.querySelector(':scope > small').innerText,price:Number(row.querySelector('strong').childNodes[0].textContent.replaceAll(',',''))}))");
    assert.equal(indices.length,2);indices.forEach((row,index)=>{assert.ok(row.date.includes(date));assert.equal(row.price,day.markets[index].index.close);});
    const totals=await evaluate("[...document.querySelectorAll('.investorSummary article > strong')].map(node=>Number(node.childNodes[0].textContent.replaceAll(',','')))");
    assert.deepEqual(totals,["personal","foreign","institution"].map(key=>Number((day.markets.filter(value=>market==="all"||value.market===market).reduce((sum,value)=>sum+value.investors.find(row=>row.key===key).net,0)/1e8).toFixed(2))));
  };
  await send("Runtime.enable");await send("Network.enable");
  await navigate("/investor-flows");await verify(archive.latest_date);
  assert.equal(await evaluate("document.querySelectorAll('.investorHistoryTable tbody tr').length"),archive.history.filter(row=>row.date.startsWith(archive.latest_date.slice(0,7))).length);
  await evaluate("(()=>{const input=document.querySelector('.sectorCalendarNavigation input');Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,'2023-01');input.dispatchEvent(new Event('input',{bubbles:true}));})()");
  await until(()=>evaluate("Boolean(document.querySelector('[data-date=\"2023-01-02\"]'))"),"January 2023 calendar unavailable");
  assert.equal(await evaluate("document.querySelector('[data-date=\"2023-01-01\"]').disabled"),true);
  assert.equal(await evaluate("document.querySelector('[data-date=\"2023-01-07\"]').disabled"),true);
  await click('[data-date="2023-01-02"]');await verify("2023-01-02");
  await evaluate("[...document.querySelectorAll('[aria-label=\"조회 시장\"] button')].find(node=>node.innerText==='코스닥').click()");await verify("2023-01-02","KOSDAQ");
  assert.equal(await evaluate("new URL(location.href).searchParams.get('date')"),"2023-01-02");
  const before=responses.length;await click(".refreshButton");
  await until(()=>Promise.resolve(responses.slice(before).some(row=>row.date==="2023-01-02"&&row.status===200)),"Historical original refresh failed");
  await until(()=>evaluate("!document.querySelector('.refreshButton').disabled"),"Historical original refresh did not finish");await verify("2023-01-02","KOSDAQ");
  for(const width of [1440,390,320]) {
    await send("Emulation.setDeviceMetricsOverride",{width,height:1000,deviceScaleFactor:1,mobile:false});
    assert.equal(await evaluate("document.documentElement.scrollWidth>innerWidth"),false,`Investor page overflows at ${width}px`);
    await evaluate("document.querySelector('.investorDateHeading').scrollIntoView({block:'start'})");
    const image=await send("Page.captureScreenshot",{format:"png"}),folder=new URL("../../data/tmp_2023/ui/",import.meta.url);await mkdir(folder,{recursive:true});await writeFile(new URL(`investors-${width}.png`,folder),Buffer.from(image.data,"base64"));
  }
  await click(".sectorCalendarHeading button");await verify(archive.latest_date,"KOSDAQ");
  await navigate("/investor-flows?date=2023-01-01");await until(()=>evaluate("document.querySelector('.errorNotice')?.innerText.includes('기록이 없습니다')"),"Invalid trading date fell back silently");assert.equal(await evaluate("document.querySelectorAll('.investorIndices > button').length"),0);
  await navigate("/investor-flows?date=2023-01-02&market=KOSPI");await verify("2023-01-02","KOSPI");
  const retained=await evaluate("document.querySelector('.investorFlowTable tbody').innerText");
  socket.addEventListener("message",event=>{const value=JSON.parse(event.data);if(value.method==="Fetch.requestPaused"){const preflight=value.params.request.method==="OPTIONS";void send("Fetch.fulfillRequest",{requestId:value.params.requestId,responseCode:preflight?204:502,responseHeaders:[{name:"Content-Type",value:"application/json"},{name:"Access-Control-Allow-Origin",value:new URL(base).origin},{name:"Access-Control-Allow-Methods",value:"POST, OPTIONS"},{name:"Access-Control-Allow-Headers",value:"Content-Type"}],body:preflight?"":Buffer.from(JSON.stringify({error:"의도한 원본 조회 실패"})).toString("base64")});}});
  await send("Fetch.enable",{patterns:[{urlPattern:"*/refresh",requestStage:"Request"}]});await click(".refreshButton");await until(()=>evaluate("document.querySelector('.errorNotice')?.innerText.includes('의도한 원본 조회 실패')"),"Source failure did not appear");assert.equal(await evaluate("document.querySelector('.investorFlowTable tbody').innerText"),retained);
  assert.deepEqual(exceptions,[]);console.log(JSON.stringify({result:"PASS",dates:archive.history.length,checks:"Exact-date gross buys/sells/net flows and both indices, market totals, 2023 calendar/closures, URL selection, original historical refresh, failure retention, 1440/390/320px"}));
} finally {
  if(send&&socket?.readyState===WebSocket.OPEN)await send("Browser.close").catch(()=>{});socket?.close();browser.kill();assert.ok(resolve(profile).startsWith(resolve(tmpdir())+sep));await rm(profile,{recursive:true,force:true,maxRetries:10,retryDelay:100});
}
