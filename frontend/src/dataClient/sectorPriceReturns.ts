import type { SectorPeriod, SectorSnapshot, SectorStock } from "./sectorRankings";
import type { StockHistory } from "./stockHistoryClient";
import { atOrBefore, loadSectorHistories } from "./sectorExplorer";

const DAY = 86400000;
const periods = ["day", "week", "month", "quarter", "year"] as const;
export const emptySectorReturns = (): Record<SectorPeriod, number | null> => ({ day: null, week: null, month: null, quarter: null, year: null });
const isoDay = (date: Date) => date.toISOString().slice(0, 10);
const positive = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value) && value > 0;

export function returnReferenceDates(date: string) {
  const end = Date.parse(date);
  function monthsAgo(months: number) {
    const start = new Date(end);
    const day = start.getUTCDate();
    start.setUTCMonth(start.getUTCMonth() - months, 1);
    const lastDay = new Date(start.getTime());
    lastDay.setUTCMonth(lastDay.getUTCMonth() + 1, 0);
    start.setUTCDate(Math.min(day, lastDay.getUTCDate()));
    return isoDay(start);
  }
  return { day: isoDay(new Date(end - DAY)), week: isoDay(new Date(end - 7 * DAY)), month: monthsAgo(1), quarter: monthsAgo(3), year: monthsAgo(12) };
}

function closedPrices(value: StockHistory) {
  const prices = value.history;
  const last = prices.at(-1);
  if (!last) return prices;
  const openDay = Date.parse(last.date) - 9 * 3600000;
  const standardClose = Date.parse(last.date) + 6.5 * 3600000;
  const collected = Date.parse(value.fetched_at ?? "");
  return collected >= openDay && collected < standardClose ? prices.slice(0, -1) : prices;
}

function observedQuoteScale(prices: ReturnType<typeof closedPrices>, quotes: {date: string; close: number}[], end: string) {
  const ratios: number[] = [];
  for (let i = quotes.length - 1; i >= 0 && ratios.length < 3; i--) {
    const quote = quotes[i];
    if (quote.date >= end) continue;
    const bar = atOrBefore(prices, quote.date);
    if (bar?.date === quote.date && positive(bar.adjusted_close) && positive(quote.close)) ratios.push(bar.adjusted_close / quote.close);
  }
  const scale = ratios[0];
  return ratios.length === 3 && ratios.every(value => Math.abs(value / scale - 1) <= 0.001) ? scale : null;
}

export function priceSectorMembers(snapshot: SectorSnapshot, stocks: SectorStock[], histories: StockHistory[]): SectorStock[] {
  const {date} = snapshot;
  const references = returnReferenceDates(date);
  const useQuotes = !snapshot.reconstruction && snapshot.source === "TradingView";
  const preferQuote = !snapshot.archived;
  const available = new Map(histories.filter(value => value.currency === "KRW").map(value => [value.ticker, value]));
  return stocks.map(stock => {
    const returns = emptySectorReturns();
    const value = available.get(stock.ticker);
    if (!value || stock.date !== date) return { ...stock, change_pct: null, returns };
    const primary = closedPrices(value);
    const prior = (value.prior_snapshots ?? [])
      .filter(curve => curve.complete_history && curve.ticker === value.ticker && curve.currency === "KRW")
      .map(curve => closedPrices({...curve, history: curve.prices.map(([day, close, adjusted_close]) => ({date: day, close, adjusted_close, volume: null}))}));
    const exact = [primary, ...prior].flatMap(prices => {
      const end = atOrBefore(prices, date);
      return end?.date === date && positive(end.adjusted_close) ? [{prices, price: end.adjusted_close}] : [];
    });
    const quotes = (value.sector_quotes ?? []).map(([date, close]) => ({date, close}));
    const quoteEnd = atOrBefore(quotes, date);
    const allowQuote = useQuotes && (preferQuote || quoteEnd?.date === date);
    const scale = allowQuote ? observedQuoteScale(primary, quotes, date) : null;
    for (const period of periods) {
      const target = references[period];
      const quote = atOrBefore(quotes, target);
      const quoteReturn = allowQuote && quote && positive(quote.close) && Date.parse(target) - Date.parse(quote.date) <= 7 * DAY
        ? stock.price / quote.close - 1 : null;
      let savedReturn = null;
      for (const curve of exact) {
        const base = atOrBefore(curve.prices, target)?.adjusted_close;
        if (positive(base)) { savedReturn = curve.price / base - 1; break; }
      }
      const base = atOrBefore(primary, target)?.adjusted_close;
      const linked = positive(scale) && positive(base) ? stock.price * scale / base - 1 : null;
      const result = preferQuote && quoteReturn !== null ? quoteReturn : savedReturn ?? quoteReturn ?? linked;
      if (result !== null && Number.isFinite(result)) returns[period] = result * 100;
    }
    return { ...stock, change_pct: returns.day, returns };
  });
}

export async function loadSectorReturns(snapshot: SectorSnapshot, stocks: SectorStock[], signal: AbortSignal) {
  const {values, errors} = await loadSectorHistories(stocks, signal);
  return { stocks: priceSectorMembers(snapshot, stocks, values), errors };
}
