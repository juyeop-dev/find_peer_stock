import { getPublishedStockHistory, getStockHistory } from "./stockHistoryClient";
import { validateReplayMarket } from "./chartReplay";
import type { ReplayMarket } from "./chartReplay";

let snapshot: Promise<ReplayMarket[]> | undefined;
function getReplayMarkets() {
  if (!snapshot) snapshot = (async () => {
    const response = await fetch(`${import.meta.env.BASE_URL}data/chart-replay/markets.json`);
    if (!response.ok) throw new Error("시장 차트 자료를 불러오지 못했습니다. 다시 시도해 주세요.");
    const data = await response.json();
    if (data.schema_version !== 1 || !Array.isArray(data.markets)) throw new Error("시장 차트 자료의 형식이 올바르지 않습니다.");
    return data.markets.map(validateReplayMarket) as ReplayMarket[];
  })().catch(error => { snapshot = undefined; throw error; });
  return snapshot;
}
export async function getReplayMarket(ticker: string, name: string, exchange?: string, signal?: AbortSignal): Promise<ReplayMarket> {
  if (["^KS11", "GC=F"].includes(ticker)) {
    const market = (await getReplayMarkets()).find(row => row.ticker === ticker);
    if (!market) throw new Error(`${name}의 저장 차트가 없습니다.`);
    return market;
  }
  // Replay uses durable history first. Current quote refreshes must not replace
  // the historical window while a replay is running.
  let stock;
  try { stock = await getPublishedStockHistory(ticker, signal); }
  catch (error) {
    if (signal?.aborted) throw error;
    stock = await getStockHistory(ticker, exchange, signal);
  }
  return validateReplayMarket({ ticker, name, currency: stock.currency, source: stock.source, bars: stock.history });
}
