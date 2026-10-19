import type { SemiconductorPrice } from "./semiconductorTypes";
import { liveDetailFor, requestOriginal } from "./liveStockDataClient";

export interface StockHistory {
  ticker: string; currency: string; source: string; fetched_at?: string; first_trade_date?: string | null;
  history: SemiconductorPrice[]; warning?: string;
}
export const CHART_PERIODS = [7, 30, 90, 180, "1y", "2y", "since2025"] as const;
export type ChartPeriod = typeof CHART_PERIODS[number];
export const chartPeriodLabel = (period: ChartPeriod) => typeof period === "number" ? `${period}일` : period === "since2025" ? "2025년~" : period === "1y" ? "1년" : "2년";
export function chartStart(end: string, period: ChartPeriod): string {
  if (period === "since2025") return "2025-01-01";
  const day = new Date(`${end}T12:00:00Z`);
  if (typeof period === "number") day.setUTCDate(day.getUTCDate() - period);
  else {
    const month = day.getUTCMonth();
    day.setUTCFullYear(day.getUTCFullYear() - (period === "1y" ? 1 : 2));
    if (day.getUTCMonth() !== month) day.setUTCDate(0); // Feb 29 -> Feb 28.
  }
  return day.toISOString().slice(0, 10);
}
export function historyRange(history: SemiconductorPrice[], period: ChartPeriod): SemiconductorPrice[] {
  if (!history.length) return [];
  const start = chartStart(history.at(-1)!.date, period);
  const anchor = [...history].reverse().find(point => point.date <= start)?.date ?? history[0].date;
  return history.filter(point => point.date >= anchor);
}
export function yearCovered(history: SemiconductorPrice[]): boolean {
  return history.length >= 2 && history[0].date <= chartStart(history.at(-1)!.date, "1y");
}
const histories = new Map<string, StockHistory>();
const insufficient = "제공처에서 최근 1년 전체 일봉을 확인하지 못했습니다. 확인된 기간만 표시합니다.";

function validate(value: StockHistory, ticker: string): StockHistory {
  if (value.ticker.toUpperCase() !== ticker.toUpperCase() || !value.currency || !Array.isArray(value.history) || value.history.length < 2) throw new Error("종목 일봉을 확인할 수 없습니다.");
  let previous = "";
  for (const point of value.history) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(point.date) || point.date <= previous || !Number.isFinite(point.close) || point.close <= 0) throw new Error("일봉 날짜 또는 가격이 올바르지 않습니다.");
    previous = point.date;
  }
  return value;
}
export async function refreshStockHistory(ticker: string, exchange?: string, signal?: AbortSignal): Promise<StockHistory> {
  const response = await requestOriginal<{ items: StockHistory[]; errors: { message: string }[] }>({ kind: "history", stocks: [{ ticker: ticker.toUpperCase(), ...(exchange ? { exchange } : {}) }] }, signal);
  const fresh = validate(response.items[0], ticker);
  histories.set(ticker.toUpperCase(), fresh);
  return fresh;
}
export async function getStockHistory(ticker: string, exchange?: string, signal?: AbortSignal, fromSource = false, initial?: StockHistory, onCached?: (value: StockHistory) => void): Promise<StockHistory> {
  if (fromSource) return refreshStockHistory(ticker, exchange, signal);
  const detail = liveDetailFor(ticker);
  let base = detail?.history?.length ? { ticker, currency: detail.quote.currency, source: detail.quote.source,
    fetched_at: detail.fetched_at, history: detail.history } : histories.get(ticker.toUpperCase()) ?? initial;
  if (!base) {
    try {
      const filename = encodeURIComponent(ticker.toUpperCase()).replaceAll("%", "~");
      const response = await fetch(`${import.meta.env.BASE_URL}data/stock-history/${filename}.json?t=${Date.now()}`, { signal, cache: "no-store" });
      if (!response.ok) throw new Error("저장된 일봉 없음");
      const packed = await response.json();
      base = validate({ ...packed, history: packed.prices.map(([date, close, adjusted_close]: [string, number, number]) => ({ date, close, adjusted_close, volume: null })) }, ticker);
    } catch (error) { if (signal?.aborted) throw error; }
  }
  if (base && !signal?.aborted) onCached?.(base);
  const freshEnough = base?.history?.length && Date.now() - Date.parse(`${base.history.at(-1)!.date}T23:59:59Z`) < 7 * 86400000
    && Date.now() - Date.parse(base.fetched_at ?? "") < 6 * 3600000;
  const shortListing = Boolean(base?.first_trade_date && base.history.length && base.first_trade_date > chartStart(base.history.at(-1)!.date, "1y"));
  if (base && freshEnough && (yearCovered(base.history) || shortListing)) return base;
  try { return await refreshStockHistory(ticker, exchange, signal); }
  catch (error) {
    if (signal?.aborted || !base) throw error;
    return { ...base, warning: yearCovered(base.history) ? "최신 일봉 조회에 실패해 저장된 가격 이력을 표시합니다." : insufficient };
  }
}
