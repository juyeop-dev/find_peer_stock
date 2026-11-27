import { requestOriginal } from "./liveStockDataClient";
import type { SectorCalendar, SectorSnapshot } from "./sectorRankings";
import { classifiedSectorStock } from "./sectorRankings";
import { emptySectorReturns, loadSectorReturns } from "./sectorPriceReturns";
import { expandSectorDay } from "../../../shared/sector-day.mjs";
import { expandSectorWeek, sectorWeekStart } from "../../../shared/sector-week.mjs";
import koreanCompanyNames from "../../../data/seed/korean_company_names.json";

let latest: SectorSnapshot | undefined;
let profiles: unknown;
export function expandSectorArchive(value: unknown): unknown {
  const packed=value as {encoding?:string;stock_fields?:unknown;stock_rows?:unknown};
  if(!packed?.encoding)return value;
  if(packed.encoding!=="sector-columns-v1"||!Array.isArray(packed.stock_fields)||!Array.isArray(packed.stock_rows))throw new Error("섹터 압축 기록 형식이 올바르지 않습니다.");
  const fields=packed.stock_fields as unknown[][];
  if(fields.some(row=>!Array.isArray(row)||!row.length||new Set(row).size!==row.length||row.some(key=>typeof key!=="string"||["__proto__","constructor","prototype"].includes(key))))throw new Error("섹터 압축 기록의 열이 올바르지 않습니다.");
  const stocks=packed.stock_rows.map((row: unknown)=>{
    if(!Array.isArray(row)||!Number.isInteger(row[0])||row[0]<0||!fields[row[0]]||row.length!==fields[row[0]].length+1)throw new Error("섹터 압축 기록의 행이 올바르지 않습니다.");
    return Object.fromEntries(fields[row[0]].map((key,index)=>[key,row[index+1]]));
  });
  const {encoding,stock_fields,stock_rows,...metadata}=packed;
  return {...metadata,stocks};
}
export function validSectorDate(value: string) {
  return /^\d{4}-\d{2}-\d{2}$/.test(value) && Number.isFinite(Date.parse(value)) && new Date(value).toISOString().slice(0, 10) === value;
}
async function staticSectorJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${import.meta.env.BASE_URL}data/sectors/${path}?t=${Date.now()}`, { cache: "no-store", signal });
  if (response.status === 404 && path.endsWith(".gz")) return staticSectorJson<T>(path.slice(0, -3), signal);
  if (!response.ok) throw new Error("해당 날짜의 저장된 섹터 기록을 불러오지 못했습니다.");
  if (path.endsWith(".gz")) return expandSectorArchive(await readSectorGzip(response)) as T;
  return response.json();
}
async function readSectorGzip(response: Response): Promise<unknown> {
  const bytes = await response.arrayBuffer();
  const magic = new Uint8Array(bytes, 0, Math.min(2, bytes.byteLength));
  if (magic[0] === 0x1f && magic[1] === 0x8b) {
    return new Response(new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip"))).json();
  }
  return JSON.parse(new TextDecoder().decode(bytes));
}
async function getDatedListing(date: string, signal?: AbortSignal) {
  const path = `${import.meta.env.BASE_URL}data/sectors/`;
  const response = await fetch(`${path}daily/${date}.json.gz`, { cache: "no-cache", signal });
  if (response.status === 404) {
    const legacy = await fetch(`${path}weekly/${sectorWeekStart(date)}.json.gz`, { cache: "no-cache", signal });
    if (legacy.ok) return { snapshot: expandSectorWeek(await readSectorGzip(legacy), date) as SectorSnapshot, current: false };
    return { snapshot: await staticSectorJson<SectorSnapshot>(`daily/${date}.json`, signal), current: false };
  }
  if (!response.ok) throw new Error("해당 날짜의 저장된 섹터 기록을 불러오지 못했습니다.");
  const value = await readSectorGzip(response) as { encoding?: string; current?: boolean };
  if (value.encoding !== "sector-day-v1") return { snapshot: expandSectorArchive(value) as SectorSnapshot, current: false };
  if (profiles) {
    try { return { snapshot: expandSectorDay(value, profiles) as SectorSnapshot, current: value.current === true }; }
    catch { /* The daily file may have been published with updated profiles. */ }
  }
  const lookup = await fetch(`${path}profiles.json.gz`, { cache: "no-cache", signal });
  if (!lookup.ok) throw new Error("섹터 종목 정보 목록을 불러오지 못했습니다.");
  profiles = await readSectorGzip(lookup);
  return { snapshot: expandSectorDay(value, profiles) as SectorSnapshot, current: value.current === true };
}
function validate(value: SectorSnapshot) {
  if (value?.schema_version !== 1 || value.market !== "korea" || value.currency !== "KRW" || !/^\d{4}-\d{2}-\d{2}$/.test(value.date) || !Number.isFinite(Date.parse(value.fetched_at)) || !Array.isArray(value.stocks) || !value.stocks.length) throw new Error("섹터 자료를 확인할 수 없습니다.");
  const tickers = new Set();
  for (const stock of value.stocks) {
    if (!stock || !/^[0-9A-Z]{6}\.(KS|KQ)$/.test(stock.ticker) || stock.currency !== "KRW" || !["KOSPI", "KOSDAQ"].includes(stock.exchange) || !Number.isFinite(stock.price) || stock.price <= 0 || typeof stock.sector !== "string" || typeof stock.industry !== "string" || tickers.has(stock.ticker)) throw new Error("종목·통화가 일치하지 않는 섹터 자료입니다.");
    tickers.add(stock.ticker);
    for (const number of [stock.turnover, stock.market_cap]) if (number !== null && (typeof number !== "number" || !Number.isFinite(number))) throw new Error("섹터 수치가 올바르지 않습니다.");
  }
  const names: Record<string, string> = koreanCompanyNames.names;
  return { ...value, stocks: value.stocks.map(stock => ({ ...stock, name: names[stock.ticker] ?? stock.name, change_pct: null, returns: emptySectorReturns() })) };
}
async function getLatestSnapshot(signal?: AbortSignal, fromSource = false): Promise<SectorSnapshot> {
  let data: SectorSnapshot;
  if (fromSource) {
    data = validate(await requestOriginal<SectorSnapshot>({ kind: "sectors" }, signal));
    data = { ...data, source_fetched_at: data.fetched_at };
  } else {
    try {
      data = validate(await staticSectorJson<SectorSnapshot>("index.json.gz", signal));
    } catch (error) {
      if (signal?.aborted) throw error;
      if (latest) return latest;
      return getLatestSnapshot(signal, true);
    }
  }
  if (!latest || Date.parse(data.fetched_at) >= Date.parse(latest.fetched_at)) latest = data;
  return latest;
}

export async function getSectorData(signal?: AbortSignal, fromSource = false): Promise<SectorSnapshot> {
  return getLatestSnapshot(signal, fromSource);
}

export async function getSectorCalendar(signal?: AbortSignal): Promise<SectorCalendar> {
  const calendar = await staticSectorJson<SectorCalendar>("calendar.json", signal);
  if (calendar?.schema_version !== 1 || calendar.market !== "korea" || !validSectorDate(calendar.latest_date) || !Array.isArray(calendar.records)
    || calendar.records.some(record => !validSectorDate(record.date) || !Number.isFinite(Date.parse(record.fetched_at)) || !(record.count > 0))
    || new Set(calendar.records.map(record => record.date)).size !== calendar.records.length) throw new Error("섹터 날짜 목록을 확인할 수 없습니다.");
  return calendar;
}
export async function getSectorSnapshot(date: string, signal?: AbortSignal, fromSource = false): Promise<SectorSnapshot> {
  if (!date) return getSectorData(signal, fromSource);
  if (!validSectorDate(date)) throw new Error("올바른 섹터 기록 날짜를 선택해 주세요.");
  const listing = await getDatedListing(date, signal);
  const snapshot = validate(listing.snapshot);
  if (snapshot.date !== date) throw new Error("선택한 날짜와 섹터 기록이 일치하지 않습니다.");
  if (listing.current && fromSource) {
    const fresh = await getLatestSnapshot(signal, true);
    if (fresh.date === date) return fresh;
    return { ...snapshot, archived: true };
  }
  return { ...snapshot, archived: !listing.current };
}
export async function getSectorStock(ticker: string, signal: AbortSignal, date = "") {
  const data = await getSectorSnapshot(date, signal);
  const stock = data.stocks.find(stock => stock.ticker === ticker.toUpperCase());
  if (!stock) throw new Error("국내 섹터 목록에서 이 종목을 찾을 수 없습니다.");
  const {stocks: [priced]} = await loadSectorReturns(data, [stock], signal);
  return { ...classifiedSectorStock(priced), market_cap_currency: "KRW", turnover_currency: "KRW", reconstruction_note: data.reconstruction?.note };
}
