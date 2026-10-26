import { readFile, mkdir, writeFile, rename } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { join,dirname } from "node:path";
import { investorFlowPage,investorIndexPage,investorRecord,INVESTOR_SOURCE,INVESTOR_START,INVESTOR_MARKETS } from "../automation/live-api/src/investors.js";
import { localDay } from "../automation/live-api/src/providers.js";

const root=fileURLToPath(new URL("../",import.meta.url)),source=join(root,"data/investors/index.json"),published=join(root,"frontend/public/data/investors/index.json");
async function save(path,value) {await mkdir(dirname(path),{recursive:true});await writeFile(path+".tmp",JSON.stringify(value)+"\n");await rename(path+".tmp",path);}
let previous;
try{previous=JSON.parse(await readFile(source,"utf8"));}catch(error){if(error.code!=="ENOENT")throw error;}
if(process.argv[2]==="publish") {
  if(!previous?.history?.length)throw new Error("Collect investor history before publishing");
  await save(published,previous);console.log(`Published ${previous.history.length} investor trading dates.`);
} else {
  const now=new Date(),today=localDay(now.getTime(),"Asia/Seoul"),hour=Number(new Intl.DateTimeFormat("en",{timeZone:"Asia/Seoul",hour:"2-digit",hourCycle:"h23"}).format(now));
  if(previous && !process.argv.includes("--full") && (hour<9 || previous.latest_date===today && previous.history.at(-1).status==="closed")) {
    await save(published,previous);console.log(`Retaining closed investor history through ${previous.latest_date}.`);
  } else {
    const start=previous&&!process.argv.includes("--full")?new Date(Date.parse(previous.latest_date)-14*86400000).toISOString().slice(0,10):INVESTOR_START;
    async function pages(market,load,first) {
      const result=[],dates=new Set();
      for(let page=first;page<first+100;page++) {
        const rows=await load(market,page);
        if(!rows.length)break;
        for(const row of rows) {if(dates.has(row.date))throw new Error(`Repeated source date ${market}/${row.date}`);dates.add(row.date);if(row.date>=start&&row.date<=today)result.push(row);}
        if(rows.at(-1).date<start)return result;
      }
      if(!result.length || result.at(-1).date>start)throw new Error(`Incomplete investor source ${market}`);
      return result;
    }
    const batches=await Promise.all(INVESTOR_MARKETS.map(async market=>{
      const [flows,indices]=await Promise.all([pages(market,investorFlowPage,0),pages(market,investorIndexPage,1)]);
      const byDate=new Map(indices.map(row=>[row.date,row]));
      return {market,rows:flows.map(flow=>{const index=byDate.get(flow.date);if(!index)throw new Error(`Missing exact index date ${market}/${flow.date}`);return {market,...flow,index};})};
    }));
    const old=new Map((previous?.history??[]).map(row=>[row.date,row]));
    const dates=[...new Set(batches.flatMap(batch=>batch.rows.map(row=>row.date)))].sort();
    for(const date of dates) {
      const markets=batches.map(batch=>batch.rows.find(row=>row.date===date));
      if(markets.some(row=>!row))throw new Error(`Incomplete market pair ${date}`);
      old.set(date,investorRecord(date,markets,now));
    }
    const history=[...old.values()].sort((a,b)=>a.date.localeCompare(b.date));
    if(!history.length)throw new Error("No investor trading dates");
    const value={schema_version:1,source:"Npay 증권 · KRX",source_url:INVESTOR_SOURCE,unit:"KRW",trade_type:"KRX",requested_start:INVESTOR_START,generated_at:now.toISOString(),latest_date:history.at(-1).date,history};
    await save(source,value);await save(published,value);console.log(`Investor history: ${history.length} dates, ${history[0].date} to ${value.latest_date}.`);
  }
}
