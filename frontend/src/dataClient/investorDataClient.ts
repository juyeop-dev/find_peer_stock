import { requestOriginal } from "./liveStockDataClient";

export type InvestorMarketKey = "KOSPI" | "KOSDAQ";
export type InvestorKey = "personal" | "foreign" | "institution" | "other";
export interface InvestorAmounts {key: InvestorKey; name: string; codes: string[]; buy: number; sell: number; net: number}
export interface InvestorIndex {date: string; close: number; change: number | null; change_pct: number | null; open: number | null; high: number | null; low: number | null}
export interface InvestorMarket {market: InvestorMarketKey; date: string; index: InvestorIndex; investors: InvestorAmounts[]; details: {code: string;name: string;buy: number;sell: number;net: number}[]}
export interface InvestorDay {date: string; status: "closed" | "provisional"; fetched_at: string; markets: InvestorMarket[]}
export interface InvestorData {schema_version: 1; source: string; source_url: string; unit: "KRW"; trade_type: "KRX"; generated_at: string; latest_date: string; history: InvestorDay[]; source_fetched_at?: string}
export const INVESTOR_LABELS: Record<InvestorKey,string> = {personal:"개인",foreign:"외국인",institution:"기관",other:"기타법인 등"};
export const INVESTOR_MARKETS = [{key:"all",label:"전체"},{key:"KOSPI",label:"코스피"},{key:"KOSDAQ",label:"코스닥"}] as const;
let cached: InvestorData | undefined, checked = 0;
export const validInvestorDate = (value: string) => /^\d{4}-\d{2}-\d{2}$/.test(value) && Number.isFinite(Date.parse(value)) && new Date(value).toISOString().slice(0,10)===value;
export function validateInvestorDay(row: InvestorDay): InvestorDay {
  if(!row || !validInvestorDate(row.date) || row.date<"2020-01-01" || row.date>new Date(Date.now()+9*3600000).toISOString().slice(0,10) || !["closed","provisional"].includes(row.status) || !Number.isFinite(Date.parse(row.fetched_at)) || !Array.isArray(row.markets) || row.markets.length!==2 || new Set(row.markets.map(value=>value.market)).size!==2)throw new Error("투자자 수급 자료의 날짜·시장을 확인할 수 없습니다.");
  for(const market of row.markets) {
    if(!["KOSPI","KOSDAQ"].includes(market.market) || market.date!==row.date || market.index?.date!==row.date || !Number.isFinite(market.index.close) || market.index.close<=0 || [market.index.change,market.index.change_pct].some(value=>value!==null&&!Number.isFinite(value)) || !Array.isArray(market.details) || !market.details.length || market.investors?.length!==4 || new Set(market.investors.map(value=>value.key)).size!==4)throw new Error("선택한 거래일의 수급과 지수가 일치하지 않습니다.");
    for(const value of market.investors)if(!Object.hasOwn(INVESTOR_LABELS,value.key)||![value.buy,value.sell,value.net].every(Number.isSafeInteger)||value.buy<0||value.sell<0)throw new Error("투자자별 매매 금액이 올바르지 않습니다.");
  }
  return row;
}
export function investorTotals(day: InvestorDay, market: string) {
  if(!INVESTOR_MARKETS.some(value=>value.key===market))throw new Error("지원하지 않는 시장입니다.");
  const selected=day.markets.filter(value=>market==="all"||value.market===market);
  return (Object.keys(INVESTOR_LABELS) as InvestorKey[]).map(key=>({key,name:INVESTOR_LABELS[key],buy:selected.reduce((sum,row)=>sum+row.investors.find(value=>value.key===key)!.buy,0),sell:selected.reduce((sum,row)=>sum+row.investors.find(value=>value.key===key)!.sell,0),net:selected.reduce((sum,row)=>sum+row.investors.find(value=>value.key===key)!.net,0)}));
}
export async function getInvestorData(signal: AbortSignal, fromSource=false, date=""): Promise<InvestorData> {
  if(fromSource) {
    const snapshot=await requestOriginal<InvestorDay & {source_fetched_at: string}>({kind:"investors",...(date?{date}:{})},signal);
    validateInvestorDay(snapshot);
    if(date && snapshot.date!==date)throw new Error("선택한 날짜와 원본 조회 결과가 일치하지 않습니다.");
    const history=[...(cached?.history??[]).filter(row=>row.date!==snapshot.date),{date:snapshot.date,status:snapshot.status,fetched_at:snapshot.fetched_at,markets:snapshot.markets}].sort((a,b)=>a.date.localeCompare(b.date));
    cached={schema_version:1,source:"Npay 증권 · KRX",source_url:"https://stock.naver.com/market/stock/kr/trend/foreigner",unit:"KRW",trade_type:"KRX",generated_at:snapshot.fetched_at,latest_date:history.at(-1)!.date,history,source_fetched_at:snapshot.source_fetched_at};
    return cached;
  }
  if(cached && Date.now()-checked<60000)return cached;
  const response=await fetch(`${import.meta.env.BASE_URL}data/investors/index.json?t=${Date.now()}`,{signal,cache:"no-store"});
  if(!response.ok)throw new Error("투자자 수급 기록을 불러오지 못했습니다.");
  const value=await response.json() as InvestorData;
  if(value?.schema_version!==1||value.unit!=="KRW"||value.trade_type!=="KRX"||!value.history?.length)throw new Error("투자자 수급 자료 형식이 올바르지 않습니다.");
  value.history.forEach(validateInvestorDay);
  const dates=value.history.map(row=>row.date);
  if(dates.some((date,index)=>index>0&&date<=dates[index-1])||value.latest_date!==dates.at(-1))throw new Error("투자자 거래일 목록이 올바르지 않습니다.");
  const merged=new Map(value.history.map(row=>[row.date,row]));
  for(const row of cached?.history??[])if(!merged.has(row.date)||Date.parse(row.fetched_at)>Date.parse(merged.get(row.date)!.fetched_at))merged.set(row.date,row);
  const history=[...merged.values()].sort((a,b)=>a.date.localeCompare(b.date));
  cached={...value,history,latest_date:history.at(-1)!.date,...(cached?.source_fetched_at?{source_fetched_at:cached.source_fetched_at}:{})};checked=Date.now();return cached;
}
export function investorMoney(value: number, signed=false) { return `${signed&&value>0?"+":""}${(value/1e8).toLocaleString("ko-KR",{minimumFractionDigits:2,maximumFractionDigits:2})}`; }
