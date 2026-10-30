import { chartStart, getPublishedStockHistory, refreshStockHistory } from "./stockHistoryClient";
import type { StockHistory } from "./stockHistoryClient";
import type { SectorPeriod, SectorStock } from "./sectorRankings";
import type { SemiconductorPrice } from "./semiconductorTypes";

const cache = new Map<string, StockHistory>();
export interface SectorHistoryProgress { checked: number; total: number; errors: number }
export function sectorHistoryForDate(value: StockHistory, end: string): StockHistory {
  if (value.history.some(point => point.date === end)) return value;
  const baseline = chartStart(end, "1y");
  const prior = value.prior_snapshots?.find(curve => curve.complete_history && curve.ticker === value.ticker && curve.currency === value.currency
    && curve.prices[0]?.[0] <= baseline && curve.prices.some(point => point[0] === end));
  if (!prior) return value;
  return {ticker: prior.ticker, currency: prior.currency, source: prior.source, fetched_at: prior.fetched_at,
    history: prior.prices.map(([date, close, adjusted_close]) => ({date, close, adjusted_close, volume: null}))};
}
export async function loadSectorHistories(stocks: SectorStock[], signal: AbortSignal, fromSource = false, onProgress?: (value: SectorHistoryProgress) => void) {
  const values: StockHistory[] = [];
  let cursor = 0, checked = 0, errors = 0;
  await Promise.all(Array.from({length: Math.min(fromSource ? 3 : 6, stocks.length)}, async () => {
    while (cursor < stocks.length) {
      signal.throwIfAborted();
      const stock = stocks[cursor++];
      try {
        const loaded = fromSource ? await refreshStockHistory(stock.ticker, stock.exchange, signal) : cache.get(stock.ticker) ?? await getPublishedStockHistory(stock.ticker, signal);
        const candidate = sectorHistoryForDate(loaded, stock.date);
        const previous = cache.get(stock.ticker);
        const history = !candidate.history.some(point => point.date === stock.date) && previous?.history.some(point => point.date === stock.date) ? previous : candidate;
        if (history.currency !== "KRW") throw new Error("이력 통화가 일치하지 않습니다.");
        cache.set(stock.ticker, history); values.push(history);
      } catch (error) {
        if (signal.aborted) throw error;
        errors++;
        const previous = cache.get(stock.ticker);
        if (previous) values.push(previous);
      }
      checked++;
      onProgress?.({checked, total: stocks.length, errors});
    }
  }));
  return {values, errors};
}

function atOrBefore(points: SemiconductorPrice[], date: string) {
  let left = 0, right = points.length - 1, found = -1;
  while (left <= right) {
    const mid = (left + right) >>> 1;
    if (points[mid].date <= date) { found = mid; left = mid + 1; } else right = mid - 1;
  }
  return found >= 0 ? points[found] : undefined;
}
export function sectorHistorySeries(histories: StockHistory[], period: SectorPeriod, end: string) {
  const start = period === "day" ? new Date(Date.parse(`${end}T12:00:00Z`) - 86400000).toISOString().slice(0, 10)
    : chartStart(end, period === "year" ? "1y" : ({week: 7, month: 30, quarter: 90} as const)[period]);
  const eligible = histories.flatMap(value => {
    const prices = value.history.filter(point => point.date <= end);
    const base = atOrBefore(prices, start);
    // Keep a fixed cohort for the complete period. A newly listed or stale
    // stock cannot silently change the weights halfway through the chart.
    return value.currency === "KRW" && base && base.adjusted_close > 0 && prices.at(-1)?.date === end
      ? [{prices, base: base.adjusted_close}] : [];
  });
  const dates = [...new Set(eligible.flatMap(value => value.prices.filter(point => point.date >= start).map(point => point.date)))].sort();
  const points = dates.map(date => ({date, value: eligible.reduce((sum, value) => sum + atOrBefore(value.prices, date)!.adjusted_close / value.base * 100, 0) / eligible.length}));
  return {points, count: eligible.length, start, end};
}
