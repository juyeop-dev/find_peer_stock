import { requestOriginal, rememberInformationQuote } from "./liveStockDataClient";
import type { LiveQuote } from "./liveStockDataClient";

export interface StockStatement {
  type: "annual" | "quarterly" | "semiannual";
  period_end: string; currency: string; source: string;
  revenue?: number | null; operating_income?: number | null; net_income?: number | null;
  total_assets?: number | null; total_debt?: number | null; operating_cash_flow?: number | null; free_cash_flow?: number | null;
}
export interface StockInformation {
  ticker: string; requested_start: string; fetched_at: string; financials_fetched_at?: string;
  source_symbol?: string; company?: { description?: string; sector?: string; industry?: string; number_of_employees?: number };
  quote: LiveQuote | null; metrics: Record<string, number | null>; metrics_currency?: string;
  financials: StockStatement[]; warnings: string[];
  historical_financials_warning?: string;
  financial_coverage?: {first_period: string | null; latest_period: string | null; note: string};
}
const snapshots = new Map<string, StockInformation>();
const checkedAt = new Map<string, number>();
export const informationFor = (ticker: string) => snapshots.get(ticker.toUpperCase());
export function mergeInformation(previous: StockInformation | undefined, fresh: StockInformation): StockInformation {
  const keys = new Set(fresh.financials.map(row => `${row.type}:${row.period_end}`));
  const retained = previous?.financials.filter(row => !keys.has(`${row.type}:${row.period_end}`)) ?? [];
  return { ...fresh, quote: fresh.quote ?? previous?.quote ?? null,
    metrics: {...(previous?.metrics_currency === fresh.metrics_currency ? previous?.metrics : {}), ...Object.fromEntries(Object.entries(fresh.metrics).filter(([, value]) => value !== null))},
    financials: [...retained, ...fresh.financials].sort((a, b) => a.period_end.localeCompare(b.period_end) || a.type.localeCompare(b.type)) };
}
function validate(value: StockInformation, ticker: string) {
  if (!value || value.ticker?.toUpperCase() !== ticker.toUpperCase() || !Array.isArray(value.financials) || !Array.isArray(value.warnings)) throw new Error("종목 정보가 일치하지 않습니다.");
  if (value.quote && (value.quote.ticker?.toUpperCase() !== ticker.toUpperCase() || !Number.isFinite(value.quote.price) || value.quote.price <= 0 || !value.quote.currency)) throw new Error("종목 시세 또는 통화가 일치하지 않습니다.");
  for (const row of value.financials) {
    if (!["annual", "quarterly", "semiannual"].includes(row.type) || !/^\d{4}-\d{2}-\d{2}$/.test(row.period_end) || row.period_end < "2025-01-01" || !row.currency) throw new Error("실적 기간 또는 통화를 확인할 수 없습니다.");
    for (const key of ["revenue", "operating_income", "net_income", "total_assets", "total_debt", "operating_cash_flow", "free_cash_flow"] as const) if (row[key] != null && !Number.isFinite(row[key])) throw new Error("재무 수치를 확인할 수 없습니다.");
  }
  return value;
}
export async function getStockInformation(ticker: string, exchange?: string, signal?: AbortSignal, fromSource = false): Promise<StockInformation> {
  const key = ticker.toUpperCase();
  let value = snapshots.get(key);
  if (fromSource) {
    const response = await requestOriginal<{items: StockInformation[]}>({kind: "information", stocks: [{ticker: key, ...(exchange ? {exchange} : {})}]}, signal);
    value = mergeInformation(value, validate(response.items[0], key));
  } else if (!value || Date.now() - (checkedAt.get(key) ?? 0) >= 60000) {
    const filename = encodeURIComponent(key).replaceAll("%", "~");
    const response = await fetch(`${import.meta.env.BASE_URL}data/stock-information/${filename}.json?t=${Date.now()}`, {signal, cache: "no-store"});
    if (!response.ok) {
      if (!value) throw new Error("저장된 종목 정보를 불러오지 못했습니다. ‘정보 다시 조회’로 원본을 조회해 주세요.");
    } else {
      const remote = validate(await response.json(), key);
      if (!value || Date.parse(remote.fetched_at) >= Date.parse(value.fetched_at)) value = mergeInformation(value, remote);
    }
  }
  if (!value) throw new Error("종목 정보를 확인할 수 없습니다.");
  snapshots.set(key, value);
  checkedAt.set(key, Date.now());
  if (value.quote) rememberInformationQuote(value.quote);
  return value;
}
