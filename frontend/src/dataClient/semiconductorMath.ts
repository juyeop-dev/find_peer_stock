import type { SemiconductorPrice, SemiconductorStock } from "./semiconductorTypes";

export const PERIODS = [7, 30, 90, 180, 360] as const;
export type Period = typeof PERIODS[number];

export function effectiveHistory(stock: SemiconductorStock): SemiconductorPrice[] {
  const history = stock.history.slice();
  const { quote } = stock;
  const date = quote.provider_time?.slice(0, 10);
  if (!date || quote.status !== "ok" || quote.price === null || quote.price <= 0) return history;
  const latest = history.at(-1);
  if (!latest || date < latest.date) return history;
  const factor = latest.adjusted_close / latest.close;
  const point = { date, close: quote.price, adjusted_close: quote.price * factor,
                  volume: date === latest.date ? latest.volume : null };
  if (date === latest.date) history[history.length - 1] = point;
  else history.push(point);
  return history;
}

export function priceOnDate(stock: SemiconductorStock, date: string): SemiconductorPrice | null {
  return effectiveHistory(stock).find((price) => price.date === date) ?? null;
}

function dateMinusDays(date: string, days: number): string {
  const value = new Date(`${date}T12:00:00Z`);
  value.setUTCDate(value.getUTCDate() - days);
  return value.toISOString().slice(0, 10);
}

function atOrBefore(history: SemiconductorPrice[], date: string): SemiconductorPrice | null {
  for (let i = history.length - 1; i >= 0; i -= 1) {
    if (history[i].date <= date) return history[i];
  }
  return null;
}

export function stockReturn(stock: SemiconductorStock, days: number, asOf?: string): number | null {
  const history = effectiveHistory(stock).filter((point) => !asOf || point.date <= asOf);
  const end = history.at(-1);
  if (!end) return null;
  const start = atOrBefore(history, dateMinusDays(end.date, days));
  if (!start || start.adjusted_close <= 0 || start.date === end.date) return null;
  return (end.adjusted_close / start.adjusted_close - 1) * 100;
}

export function sectorReturn(stocks: SemiconductorStock[], days: number, asOf?: string) {
  const values = stocks.map((stock) => stockReturn(stock, days, asOf)).filter((value): value is number => value !== null);
  return { value: values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null,
           count: values.length, total: stocks.length };
}

export interface ChartPoint { date: string; value: number }

export function stockSeries(stock: SemiconductorStock, days: number): ChartPoint[] {
  const history = effectiveHistory(stock);
  const end = history.at(-1);
  if (!end) return [];
  const start = atOrBefore(history, dateMinusDays(end.date, days));
  if (!start || start.adjusted_close <= 0) return [];
  return history.filter((point) => point.date >= start.date).map((point) => ({
    date: point.date, value: point.adjusted_close / start.adjusted_close * 100,
  }));
}

export function stockPriceSeries(stock: SemiconductorStock, days: number): ChartPoint[] {
  const normalized = stockSeries(stock, days);
  const byDate = new Map(effectiveHistory(stock).map((point) => [point.date, point.close]));
  return normalized.map((point) => ({ date: point.date, value: byDate.get(point.date) ?? 0 }));
}

export function sectorSeries(stocks: SemiconductorStock[], days: number): ChartPoint[] {
  const histories = stocks.map(effectiveHistory).filter((history) => history.length > 1);
  const latest = histories.map((history) => history.at(-1)!.date).sort().at(-1);
  if (!latest) return [];
  const anchor = dateMinusDays(latest, days);
  const eligible = histories.map((history) => ({ history, base: atOrBefore(history, anchor) }))
    .filter((item): item is { history: SemiconductorPrice[]; base: SemiconductorPrice } =>
      item.base !== null && item.base.adjusted_close > 0 && item.history.at(-1)!.date >= anchor);
  if (!eligible.length) return [];
  const dates = [...new Set(eligible.flatMap(({ history }) => history.filter((point) => point.date >= anchor).map((point) => point.date)))].sort();
  return dates.map((date) => {
    const values = eligible.map(({ history, base }) => {
      const point = atOrBefore(history, date);
      return point ? point.adjusted_close / base.adjusted_close * 100 : null;
    }).filter((value): value is number => value !== null);
    return { date, value: values.reduce((sum, value) => sum + value, 0) / values.length };
  });
}

export function formatWon(value: number | null | undefined): string {
  return value === null || value === undefined ? "-" : `${Math.round(value).toLocaleString("ko-KR")}원`;
}

export function formatPercent(value: number | null | undefined): string {
  return value === null || value === undefined ? "-" : `${value > 0 ? "+" : ""}${value.toFixed(2)}%`;
}

export function formatEok(value: number | null | undefined): string {
  return value === null || value === undefined ? "-" : `${Math.round(value).toLocaleString("ko-KR")}억`;
}
