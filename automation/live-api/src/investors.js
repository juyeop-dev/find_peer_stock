import { jsonSource, localDay, numeric } from "./providers.js";

export const INVESTOR_START = "2023-01-01";
export const INVESTOR_MARKETS = ["KOSPI", "KOSDAQ"];
export const INVESTOR_SOURCE = "https://stock.naver.com/market/stock/kr/trend/foreigner";
const names = {1000:"금융투자",2000:"보험",3000:"투신",3100:"사모",4000:"은행",5000:"기타금융",6000:"연기금 등",7000:"국가·지자체",7100:"기타법인",8000:"개인",9000:"외국인",9001:"기타외국인"};
const institutionCodes = ["1000","2000","3000","3100","4000","5000","6000","7000"];
export function investorDate(raw) {
  const value = /^\d{8}$/.test(raw ?? "") ? `${raw.slice(0,4)}-${raw.slice(4,6)}-${raw.slice(6)}` : raw;
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value) || !Number.isFinite(Date.parse(value)) || new Date(value).toISOString().slice(0,10) !== value) throw new Error("Invalid investor date");
  return value;
}
export function parseInvestorFlow(row) {
  const date = investorDate(row?.bizdate);
  if (!Array.isArray(row.netAmounts) || row.netAmounts.length < 4) throw new Error("Missing investor amounts");
  const seen = new Set();
  const details = row.netAmounts.filter(value => !["7050","9999"].includes(String(value.investorGubun))).map(value => {
    const code = String(value.investorGubun), buy = numeric(value.buyPrice), sell = numeric(value.sellPrice), net = numeric(value.diffValue);
    if (seen.has(code) || !/^\d{4}$/.test(code) || ![buy,sell,net].every(Number.isSafeInteger) || buy < 0 || sell < 0 || Math.abs(buy-sell-net) > 1e6) throw new Error("Invalid investor buy/sell amounts");
    seen.add(code);
    return {code, name:names[code] ?? `기타 (${code})`, buy, sell, net};
  }).sort((a,b)=>a.code.localeCompare(b.code));
  if (!seen.has("8000") || !seen.has("9000") || !institutionCodes.some(code=>seen.has(code))) throw new Error("Missing investor groups");
  const aggregate = (key, name, codes) => ({key,name,codes,buy:details.filter(row=>codes.includes(row.code)).reduce((sum,row)=>sum+row.buy,0),sell:details.filter(row=>codes.includes(row.code)).reduce((sum,row)=>sum+row.sell,0),net:details.filter(row=>codes.includes(row.code)).reduce((sum,row)=>sum+row.net,0)});
  const known = new Set(["8000","9000","9001",...institutionCodes]);
  const investors = [aggregate("personal","개인",["8000"]),aggregate("foreign","외국인",["9000","9001"]),aggregate("institution","기관",institutionCodes),aggregate("other","기타법인 등",details.filter(row=>!known.has(row.code)).map(row=>row.code))];
  if (Math.abs(investors.reduce((sum,row)=>sum+row.net,0)) > details.length*1e6) throw new Error("Investor market totals do not balance");
  return {date,investors,details};
}
export function parseInvestorIndex(row) {
  const date=investorDate(row?.localTradedAt), close=numeric(row.closePrice);
  if (close === null || close <= 0) throw new Error("Invalid dated market index");
  const falling = row.compareToPreviousPrice?.code === "5" || row.compareToPreviousPrice?.name === "FALLING";
  const signed = value => { const n=numeric(value);return n===null?null:falling?-Math.abs(n):n; };
  return {date,close,change:signed(row.compareToPreviousClosePrice),change_pct:signed(row.fluctuationsRatio),open:numeric(row.openPrice),high:numeric(row.highPrice),low:numeric(row.lowPrice)};
}
export async function investorFlowPage(market, page, fetcher=fetch) {
  if (!INVESTOR_MARKETS.includes(market)) throw new Error("Unknown investor market");
  const query=new URLSearchParams({tradeType:"KRX",marketType:market,startIdx:String(page),pageSize:"200"});
  const payload=await jsonSource(`https://stock.naver.com/api/domestic/market/trend/daily?${query}`,undefined,fetcher);
  if (!Array.isArray(payload?.content)) throw new Error("Investor daily source unavailable");
  return payload.content.map(parseInvestorFlow);
}
export async function investorIndexPage(market, page, fetcher=fetch) {
  if (!INVESTOR_MARKETS.includes(market)) throw new Error("Unknown index market");
  const rows=await jsonSource(`https://m.stock.naver.com/api/index/${market}/price?pageSize=60&page=${page}`,undefined,fetcher);
  if (!Array.isArray(rows)) throw new Error("Index daily source unavailable");
  return rows.map(parseInvestorIndex);
}
export function investorRecord(date, markets, now=new Date()) {
  const today=localDay(now.getTime(),"Asia/Seoul");
  const hour=Number(new Intl.DateTimeFormat("en",{timeZone:"Asia/Seoul",hour:"2-digit",hourCycle:"h23"}).format(now));
  if (date > today || markets.some(market=>market.date!==date || market.index?.date!==date)) throw new Error("Investor/index date mismatch");
  return {date,status:date===today&&hour<19?"provisional":"closed",fetched_at:now.toISOString(),markets};
}
async function exactDate(date, market, load, size, firstPage, fetcher) {
  // These endpoints ignore a requested bizdate. Match the returned date,
  // and move to an adjacent page rather than silently displaying latest data.
  const today=localDay(Date.now(),"Asia/Seoul");
  let page=firstPage+Math.floor((Date.parse(today)-Date.parse(date))/86400000*.67/size);
  const visited=new Set();
  for (let attempt=0;attempt<6;attempt++) {
    if (visited.has(page) || page<firstPage) break;
    visited.add(page);
    const rows=await load(market,page,fetcher);
    const match=rows.find(row=>row.date===date);
    if(match)return match;
    if(!rows.length) {page--;continue;}
    if(date<rows.at(-1).date)page++;else if(date>rows[0].date)page--;else break;
  }
  throw new Error("Requested trading date unavailable");
}
export async function investorSnapshot(date, fetcher=fetch) {
  const now=new Date(), today=localDay(now.getTime(),"Asia/Seoul");
  if(date && (investorDate(date)<INVESTOR_START || date>today))throw new Error("Unsupported investor date");
  if(!date) {
    const [a,b,c,d]=await Promise.all([investorFlowPage("KOSPI",0,fetcher),investorFlowPage("KOSDAQ",0,fetcher),investorIndexPage("KOSPI",1,fetcher),investorIndexPage("KOSDAQ",1,fetcher)]);
    date=a.find(row=>b.some(other=>other.date===row.date)&&c.some(other=>other.date===row.date)&&d.some(other=>other.date===row.date)&&row.date<=today)?.date;
    if(!date)throw new Error("No common investor/index trading date");
    return {schema_version:1,source:"Npay 증권 · KRX",source_url:INVESTOR_SOURCE,unit:"KRW",trade_type:"KRX",source_fetched_at:now.toISOString(),...investorRecord(date,[{market:"KOSPI",...a.find(row=>row.date===date),index:c.find(row=>row.date===date)},{market:"KOSDAQ",...b.find(row=>row.date===date),index:d.find(row=>row.date===date)}],now)};
  }
  const markets=await Promise.all(INVESTOR_MARKETS.map(async market=>{
    const [flow,index]=await Promise.all([exactDate(date,market,investorFlowPage,200,0,fetcher),exactDate(date,market,investorIndexPage,60,1,fetcher)]);
    return {market,...flow,index};
  }));
  return {schema_version:1,source:"Npay 증권 · KRX",source_url:INVESTOR_SOURCE,unit:"KRW",trade_type:"KRX",source_fetched_at:now.toISOString(),...investorRecord(date,markets,now)};
}
