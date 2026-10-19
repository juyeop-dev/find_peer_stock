import type { NewHighIndex } from "./newHighTypes";
import type { TurnoverIndex } from "./turnoverTypes";

export type HistoryKind = "new-highs" | "turnover";
export type MoneyTotals = Record<string, number>;
export interface HistoryStock {
  ticker: string;
  name: string;
  exchange: string;
  category: string;
  dates: string[];
  high_52_week: number;
  high_all_time: number;
  turnover_by_currency: MoneyTotals;
}
export interface CalendarHistory {
  schema_version: 1;
  kind: HistoryKind;
  market: string;
  year: string;
  months: { month: string; stocks: HistoryStock[] }[];
}
export interface HistoryDay {
  date: string;
  count: number;
  high52: number;
  highAll: number;
  money: MoneyTotals;
}

export function addMoney(target: MoneyTotals, source: MoneyTotals): MoneyTotals {
  for (const [currency, value] of Object.entries(source)) target[currency] = (target[currency] ?? 0) + value;
  return target;
}

export function historyDays(highs: NewHighIndex, turnover: TurnoverIndex, kind: HistoryKind, market: string): HistoryDay[] {
  return (kind === "new-highs"
    ? highs.reports.filter((report) => report.market === market).map((report) => ({
      date: report.date, count: report.counts.total, high52: report.counts.high_52_week,
      highAll: report.counts.high_all_time, money: {},
    }))
    : turnover.reports.filter((report) => report.market === market).map((report) => ({
      date: report.date, count: report.count, high52: 0, highAll: 0,
      money: report.turnover_by_currency ?? (report.currency ? { [report.currency]: report.total_turnover } : {}),
    }))).sort((a, b) => a.date.localeCompare(b.date));
}

export function summarizeDays(days: HistoryDay[]) {
  return days.reduce((total, day) => ({
    days: total.days + 1, count: total.count + day.count,
    high52: total.high52 + day.high52, highAll: total.highAll + day.highAll,
    money: addMoney(total.money, day.money),
  }), { days: 0, count: 0, high52: 0, highAll: 0, money: {} as MoneyTotals });
}

export function mergeHistoryStocks(history: CalendarHistory, prefix: string): HistoryStock[] {
  const stocks = new Map<string, HistoryStock>();
  for (const month of history.months.filter((item) => item.month.startsWith(prefix)).sort((a, b) => a.month.localeCompare(b.month))) {
    for (const item of month.stocks) {
      const previous = stocks.get(item.ticker);
      stocks.set(item.ticker, {
        ...item, dates: [...new Set([...(previous?.dates ?? []), ...item.dates])].sort(),
        high_52_week: (previous?.high_52_week ?? 0) + item.high_52_week,
        high_all_time: (previous?.high_all_time ?? 0) + item.high_all_time,
        turnover_by_currency: addMoney({ ...previous?.turnover_by_currency }, item.turnover_by_currency),
      });
    }
  }
  return [...stocks.values()].sort((a, b) => b.dates.length - a.dates.length || a.ticker.localeCompare(b.ticker));
}

export function formatHistoryMoney(totals: MoneyTotals): string {
  const format = (value: number) => new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 2 }).format(value);
  return Object.entries(totals).sort(([a], [b]) => a.localeCompare(b)).map(([currency, amount]) => {
    const value = amount >= 1e12 ? `${format(amount / 1e12)}조` : amount >= 1e8 ? `${format(amount / 1e8)}억`
      : amount >= 1e4 ? `${format(amount / 1e4)}만` : format(amount);
    return `${value} ${currency}`;
  }).join(" · ") || "—";
}
