import { requestOriginal } from "./liveStockDataClient";
import type { SectorCalendar, SectorSnapshot } from "./sectorRankings";

let latest: SectorSnapshot | undefined;
export function validSectorDate(value: string) {
  return /^\d{4}-\d{2}-\d{2}$/.test(value) && Number.isFinite(Date.parse(value)) && new Date(value).toISOString().slice(0, 10) === value;
}
async function staticSectorJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${import.meta.env.BASE_URL}data/sectors/${path}?t=${Date.now()}`, { cache: "no-store", signal });
  if (!response.ok) throw new Error("해당 날짜의 저장된 섹터 기록을 불러오지 못했습니다.");
  return response.json();
}
function validate(value: SectorSnapshot) {
  if (value?.schema_version !== 1 || value.market !== "korea" || value.currency !== "KRW" || !/^\d{4}-\d{2}-\d{2}$/.test(value.date) || !Number.isFinite(Date.parse(value.fetched_at)) || !Array.isArray(value.stocks) || !value.stocks.length) throw new Error("섹터 자료를 확인할 수 없습니다.");
  const tickers = new Set();
  for (const stock of value.stocks) {
    if (!stock || !/^[0-9A-Z]{6}\.(KS|KQ)$/.test(stock.ticker) || stock.currency !== "KRW" || !["KOSPI", "KOSDAQ"].includes(stock.exchange) || !Number.isFinite(stock.price) || stock.price <= 0 || !stock.returns || typeof stock.sector !== "string" || typeof stock.industry !== "string" || tickers.has(stock.ticker)) throw new Error("종목·통화가 일치하지 않는 섹터 자료입니다.");
    tickers.add(stock.ticker);
    for (const number of [stock.turnover, stock.market_cap, ...Object.values(stock.returns)]) if (number !== null && (typeof number !== "number" || !Number.isFinite(number))) throw new Error("섹터 수치가 올바르지 않습니다.");
  }
  return value;
}
export async function getSectorData(signal?: AbortSignal, fromSource = false): Promise<SectorSnapshot> {
  let data: SectorSnapshot;
  if (fromSource) {
    data = validate(await requestOriginal<SectorSnapshot>({ kind: "sectors" }, signal));
    data = { ...data, source_fetched_at: data.fetched_at };
  } else {
    try {
      const response = await fetch(`${import.meta.env.BASE_URL}data/sectors/index.json?t=${Date.now()}`, { cache: "no-store", signal });
      if (!response.ok) throw new Error("저장된 섹터 자료를 불러오지 못했습니다.");
      data = validate(await response.json());
    } catch (error) {
      if (signal?.aborted) throw error;
      if (latest) return latest;
      return getSectorData(signal, true);
    }
  }
  if (!latest || Date.parse(data.fetched_at) >= Date.parse(latest.fetched_at)) latest = data;
  return latest;
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
  const current = await getSectorData(signal);
  if (current.date === date) {
    if (!fromSource) return current;
    const fresh = await getSectorData(signal, true);
    if (fresh.date === date) return fresh;
    // A new trading day must not move an explicitly selected historical date.
  }
  const snapshot = validate(await staticSectorJson<SectorSnapshot>(`daily/${date}.json`, signal));
  if (snapshot.date !== date) throw new Error("선택한 날짜와 섹터 기록이 일치하지 않습니다.");
  return { ...snapshot, archived: true, source_fetched_at: undefined };
}
export async function getSectorStock(ticker: string, signal: AbortSignal, date = "") {
  const data = await getSectorSnapshot(date, signal);
  const stock = data.stocks.find(stock => stock.ticker === ticker.toUpperCase());
  if (!stock) throw new Error("국내 섹터 목록에서 이 종목을 찾을 수 없습니다.");
  return { ...stock, market_cap_currency: "KRW", turnover_currency: "KRW" };
}
