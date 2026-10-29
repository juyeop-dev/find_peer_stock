// Add only observed 2022 market pairs; retain every later stored record verbatim.
import {readFile, mkdir, writeFile, rename} from "node:fs/promises";
import {fileURLToPath} from "node:url";
import {join, dirname} from "node:path";
import {investorFlowPage, investorIndexPage, investorRecord, INVESTOR_MARKETS} from "../automation/live-api/src/investors.js";

const root=fileURLToPath(new URL("../",import.meta.url));
const start="2022-01-01", end="2022-12-31";
async function save(path,value) {
  await mkdir(dirname(path),{recursive:true});
  await writeFile(path+".tmp",JSON.stringify(value)+"\n");await rename(path+".tmp",path);
}
async function pages(market,load,first,label) {
  const result=[],seen=new Set();
  for(let page=first;page<first+100;page++) {
    const cache=join(root,`data/tmp_2022/investors/${market}-${label}-${page}.json`);
    let rows;
    try {rows=JSON.parse(await readFile(cache,"utf8"));}
    catch(error) {if(error.code!=="ENOENT")throw error;rows=await load(market,page);await save(cache,rows);}
    if(!rows.length)throw new Error(`Source ended before requested start: ${market}/${label}`);
    for(const row of rows) {
      if(seen.has(row.date))throw new Error(`Repeated source date: ${market}/${label}/${row.date}`);
      seen.add(row.date);if(row.date>=start&&row.date<=end)result.push(row);
    }
    if(rows.at(-1).date<start)return result;
  }
  throw new Error(`Incomplete historical source: ${market}/${label}`);
}
const batches=await Promise.all(INVESTOR_MARKETS.map(async market=>{
  const [flows,indices]=await Promise.all([pages(market,investorFlowPage,0,"flows"),pages(market,investorIndexPage,1,"index")]);
  const byDate=new Map(indices.map(row=>[row.date,row]));
  return {market,rows:flows.map(flow=>{
    const index=byDate.get(flow.date);if(!index)throw new Error(`Missing exact index: ${market}/${flow.date}`);
    return {market,...flow,index};
  })};
}));
const config=JSON.parse(await readFile(join(root,"data/market-closures/2022.json"),"utf8"));
const closed=new Set(config.markets.find(row=>row.market==="korea").dates?Object.keys(config.markets.find(row=>row.market==="korea").dates):[]);
const expected=[];
for(let stamp=Date.parse(start);stamp<=Date.parse(end);stamp+=86400000) {
  const day=new Date(stamp),date=day.toISOString().slice(0,10);
  if(day.getUTCDay()!==0&&day.getUTCDay()!==6&&!closed.has(date))expected.push(date);
}
for(const batch of batches) {
  if(JSON.stringify(batch.rows.map(row=>row.date).sort())!==JSON.stringify(expected))throw new Error(`Incomplete 2022 market dates: ${batch.market}`);
}
const source=join(root,"data/investors/index.json"), previous=JSON.parse(await readFile(source,"utf8"));
const history=new Map(previous.history.map(row=>[row.date,row])),now=new Date();
for(const date of expected)if(!history.has(date))history.set(date,investorRecord(date,batches.map(batch=>batch.rows.find(row=>row.date===date)),now));
const value={...previous,requested_start:start,generated_at:now.toISOString(),history:[...history.values()].sort((a,b)=>a.date.localeCompare(b.date))};
await save(source,value);await save(join(root,"frontend/public/data/investors/index.json"),value);
await save(join(root,"data/information-audit/2022/investor-progress.json"),{start,end,dates:expected.length,markets:INVESTOR_MARKETS,validated_at:now.toISOString()});
console.log(`Added verified investor flows and exact-date indices for ${expected.length} trading dates.`);
