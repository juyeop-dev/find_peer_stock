import { requestOriginal } from "./liveStockDataClient";
import type { SectorSnapshot } from "./sectorRankings";

let latest: SectorSnapshot | undefined;
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

export async function getSectorStock(ticker: string, signal: AbortSignal) {
  const data = await getSectorData(signal);
  const stock = data.stocks.find(stock => stock.ticker === ticker.toUpperCase());
  if (!stock) throw new Error("국내 섹터 목록에서 이 종목을 찾을 수 없습니다.");
  return { ...stock, market_cap_currency: "KRW", turnover_currency: "KRW" };
}
