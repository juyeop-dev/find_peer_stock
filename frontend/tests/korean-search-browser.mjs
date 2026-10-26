import assert from "node:assert/strict";
import {spawn} from "node:child_process";
import {existsSync} from "node:fs";
import {mkdtemp,readFile,rm} from "node:fs/promises";
import {tmpdir} from "node:os";
import {join,resolve,sep} from "node:path";
const base=process.env.STOCK_SITE_BASE_URL??"http://127.0.0.1:4174";
// Keep the typing regression independent of market closures, stale quotes,
// or a constituent moving to a different industry. Only this browser's
// data request is intercepted; published market data is never modified.
const today=new Date(Date.now()+9*3600000).toISOString().slice(0,10);
const target={ticker:"042700.KQ",code:"042700",name:"한미반도체",exchange:"KOSDAQ",sector:"Producer Manufacturing",industry:"Industrial Machinery",currency:"KRW",price:1000,change_pct:1,turnover:1e8,market_cap:1e12,date:today,returns:{day:1,week:1,month:1,quarter:1,year:1}};
const fixture={schema_version:1,market:"korea",currency:"KRW",date:today,fetched_at:new Date().toISOString(),source:"IME test fixture",source_url:"https://example.test/",universe:"IME typing fixture",received:1,excluded:{},stale_count:0,stocks:[target]};
const executable=process.env.BROWSER_PATH??["C:/Program Files/Google/Chrome/Application/chrome.exe","C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe","/usr/bin/chromium","/usr/bin/google-chrome"].find(existsSync);assert.ok(executable);
const profile=await mkdtemp(join(tmpdir(),"korean-search-"));
const browser=spawn(executable,["--headless=new","--disable-gpu","--no-sandbox","--no-first-run","--remote-debugging-port=0",`--user-data-dir=${profile}`,"about:blank"],{windowsHide:true,stdio:"ignore"});
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function until(check,message) {const deadline=Date.now()+60000;while(Date.now()<deadline){if(await check())return;await delay(50);}throw new Error(message);}
let socket,send;
try {
  await until(()=>existsSync(join(profile,"DevToolsActivePort")),"Browser unavailable");
  const [port]=(await readFile(join(profile,"DevToolsActivePort"),"utf8")).split(/\r?\n/),targets=await(await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  socket=new WebSocket(targets.find(value=>value.type==="page").webSocketDebuggerUrl);await new Promise(resolve=>socket.addEventListener("open",resolve,{once:true}));
  let sequence=0;const pending=new Map(),exceptions=[];
  socket.addEventListener("message",event=>{const value=JSON.parse(event.data);if(value.method==="Runtime.exceptionThrown")exceptions.push(value.params.exceptionDetails);const task=pending.get(value.id);if(!task)return;pending.delete(value.id);clearTimeout(task.timer);value.error?task.reject(new Error(value.error.message)):task.resolve(value.result);});
  send=(method,params={})=>new Promise((resolve,reject)=>{const id=++sequence,timer=setTimeout(()=>{pending.delete(id);reject(new Error(method+" timeout"));},15000);pending.set(id,{resolve,reject,timer});socket.send(JSON.stringify({id,method,params}));});
  const evaluate=async expression=>{const result=await send("Runtime.evaluate",{expression,returnByValue:true,awaitPromise:true});if(result.exceptionDetails)throw new Error(JSON.stringify(result.exceptionDetails));return result.result.value;};
  await send("Runtime.enable");
  socket.addEventListener("message",event=>{const value=JSON.parse(event.data);if(value.method==="Fetch.requestPaused")void send("Fetch.fulfillRequest",{requestId:value.params.requestId,responseCode:200,responseHeaders:[{name:"Content-Type",value:"application/json"}],body:Buffer.from(JSON.stringify(fixture)).toString("base64")}).catch(()=>{});});
  await send("Fetch.enable",{patterns:[{urlPattern:"*data/sectors/index.json*",requestStage:"Request"}]});
  const routes=[
    ["/sector-stocks",".domesticSectorExplorer input"],
    [`/sector-trends?${new URLSearchParams({sector:target.sector,group:`${target.sector}\t${target.industry}`})}`,".domesticSectorExplorer input"],
    ["/sectors",".sectorSearch input"],
  ];
  for(const [route,selector] of routes) {
    await send("Page.navigate",{url:base+route});
    await until(()=>evaluate(`Boolean(document.querySelector(${JSON.stringify(selector)}))`),route+" search unavailable");
    assert.equal(await evaluate(route==="/sectors"?"document.querySelectorAll('.sectorRankingTable tr[data-sector]').length":"document.querySelectorAll('.sectorExplorerMembers tbody tr').length"),1,"IME fixture was not used");
    await evaluate(`window.searchBox=document.querySelector(${JSON.stringify(selector)});searchBox.focus()`);
    const trace=[];
    const state=()=>evaluate("({text:searchBox.value,q:new URL(location.href).searchParams.get('q')??'',focused:document.activeElement===searchBox,caret:searchBox.selectionStart})");
    const compose=async(parts,commit)=>{
      for(const text of parts) {await send("Input.imeSetComposition",{text,selectionStart:text.length,selectionEnd:text.length});await delay(40);trace.push({composition:text,...await state()});}
      await send("Input.insertText",{text:commit});await delay(60);
    };
    await compose(["ㅎ","하","한"],"한");
    assert.equal((await state()).text,"한",route+" first syllable was duplicated: "+JSON.stringify(trace));
    await until(async()=>(await state()).q==="한",route+" first syllable did not reach the URL");
    await compose(["ㅁ","미"],"미");
    assert.equal((await state()).text,"한미",route+" duplicated Korean input: "+JSON.stringify(trace));
    assert.ok(trace.slice(0,3).every(row=>row.q===""),"Partial Hangul was published during composition: "+JSON.stringify(trace));
    assert.ok(trace.slice(3).every(row=>row.q==="한"),"Second composition interrupted the committed syllable");
    await until(async()=>{const value=await state();return value.q==="한미"&&value.focused;},route+" committed search missing");
    assert.ok(await evaluate(route==="/sectors"
      ? `[...document.querySelectorAll('.sectorRankingTable tr[data-sector]')].some(row=>row.dataset.sector===${JSON.stringify(`${target.sector}\t${target.industry}`)})`
      : "document.querySelector('.sectorExplorerMembers tbody')?.innerText.includes('한미반도체')"),route+" Korean result missing");
    await evaluate("searchBox.setSelectionRange(1,1)");
    await compose(["ㅎ","화"],"화");
    await until(async()=>(await state()).q==="한화미",route+" edited word did not reach the URL");
    assert.equal((await state()).text,"한화미");assert.equal((await state()).caret,2);
    await evaluate("searchBox.select()");await send("Input.insertText",{text:""});
    await until(async()=>(await state()).q==="",route+" clearing search failed");
    await compose(["ㅎ","하"],"");
    assert.equal((await state()).text,"");
    for(const text of ["I","S","C"])await send("Input.insertText",{text});
    await until(async()=>{const value=await state();return value.text==="ISC"&&value.q==="ISC";},route+" rapid Latin input lost characters");
    await send("Input.dispatchKeyEvent",{type:"rawKeyDown",key:"Backspace",code:"Backspace",windowsVirtualKeyCode:8});await send("Input.dispatchKeyEvent",{type:"keyUp",key:"Backspace",code:"Backspace",windowsVirtualKeyCode:8});
    await until(async()=>(await state()).text==="IS"&&(await state()).q==="IS",route+" backspace failed");
    await evaluate("(()=>{const url=new URL(location.href);url.searchParams.set('q','삼성');history.replaceState(history.state,'',url);dispatchEvent(new PopStateEvent('popstate',{state:history.state}));})()");
    await until(async()=>{const value=await state();return value.text==="삼성"&&value.q==="삼성";},route+" external URL update did not update the draft");
    await send("Page.navigate",{url:base+route+(route.includes("?")?"&":"?")+"q="+encodeURIComponent("한미")});
    await until(()=>evaluate(`document.querySelector(${JSON.stringify(selector)})?.value==='한미'`),route+" URL restoration failed");
    console.log(JSON.stringify({route,result:"PASS",input:"한미",checks:"native IME composition, commit, mid-string insertion/caret, cancellation, clear, rapid Latin, backspace, external URL changes/restoration"}));
  }
  assert.deepEqual(exceptions,[]);
} finally {
  if(send&&socket?.readyState===WebSocket.OPEN)await send("Browser.close").catch(()=>{});socket?.close();browser.kill();assert.ok(resolve(profile).startsWith(resolve(tmpdir())+sep));await rm(profile,{recursive:true,force:true,maxRetries:10,retryDelay:100});
}
