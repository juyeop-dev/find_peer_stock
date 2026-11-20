import { fetchDataAsset } from "./assetDataClient";
import { requestOriginal, rememberInformationQuote } from "./liveStockDataClient";
import type { LiveQuote } from "./liveStockDataClient";
import companyProfiles from "../../../data/seed/company_profiles.json";

export interface StockStatement {
  type: "annual" | "quarterly" | "semiannual";
  period_end: string; currency: string; source: string; source_url?: string;
  revenue?: number | null; operating_income?: number | null; net_income?: number | null;
  total_assets?: number | null; total_debt?: number | null; operating_cash_flow?: number | null; free_cash_flow?: number | null;
}
export interface HistoricalCoverage {start: string; end: string; periods: number; annual_periods: number; quarterly_periods: number; note: string}
export interface StockInformation {
  ticker: string; requested_start: string; fetched_at: string; financials_fetched_at?: string;
  source_symbol?: string; company?: { description?: string; sector?: string; industry?: string; number_of_employees?: number | null;
    employees_as_of?: string; employees_scope?: string; employees_source?: string; employees_source_url?: string };
  quote: LiveQuote | null; metrics: Record<string, number | null>; metrics_currency?: string;
  financials: StockStatement[]; warnings: string[];
  historical_financials_warning?: string;
  [key: `historical_${string}_coverage`]: HistoricalCoverage | undefined;
  [key: `historical_${string}_fetched_at`]: string | undefined;
  financial_coverage?: {first_period: string | null; latest_period: string | null; note: string};
}
const snapshots = new Map<string, StockInformation>();
const checkedAt = new Map<string, number>();
export const informationFor = (ticker: string) => snapshots.get(ticker.toUpperCase());
function retainedCoverage(coverage: StockInformation["historical_2021_coverage"], financials: StockStatement[]) {
  if (!coverage) return coverage;
  const rows = financials.filter(row => row.period_end >= coverage.start && row.period_end <= coverage.end);
  return {...coverage, periods: rows.length, annual_periods: rows.filter(row => row.type === "annual").length,
    quarterly_periods: rows.filter(row => row.type === "quarterly").length};
}
export function mergeInformation(previous: StockInformation | undefined, fresh: StockInformation): StockInformation {
  const keys = new Set(fresh.financials.map(row => `${row.type}:${row.period_end}`));
  const retained = previous?.financials.filter(row => !keys.has(`${row.type}:${row.period_end}`)) ?? [];
  const financials = [...retained, ...fresh.financials].sort((a, b) => a.period_end.localeCompare(b.period_end) || a.type.localeCompare(b.type));
  const coverage: Partial<StockInformation> = {};
  for (const key of new Set([...Object.keys(previous ?? {}), ...Object.keys(fresh)])) {
    if (/^historical_\d{4}(?:_(?:h2|\d{4}|onward))?_coverage$/.test(key)) {
      const name = key as `historical_${string}_coverage`;
      coverage[name] = retainedCoverage(fresh[name] ?? previous?.[name], financials);
    } else if (/^historical_\d{4}(?:_(?:h2|\d{4}|onward))?_fetched_at$/.test(key)) {
      const name = key as `historical_${string}_fetched_at`;
      coverage[name] = fresh[name] ?? previous?.[name];
    }
  }
  return { ...fresh, ...coverage,
    quote: fresh.quote ?? previous?.quote ?? null,
    metrics: {...(previous?.metrics_currency === fresh.metrics_currency ? previous?.metrics : {}), ...Object.fromEntries(Object.entries(fresh.metrics).filter(([, value]) => value !== null))},
    financials };
}
function validate(value: StockInformation, ticker: string) {
  if (!value || value.ticker?.toUpperCase() !== ticker.toUpperCase() || !Array.isArray(value.financials) || !Array.isArray(value.warnings)) throw new Error("종목 정보가 일치하지 않습니다.");
  if (value.quote && (value.quote.ticker?.toUpperCase() !== ticker.toUpperCase() || !Number.isFinite(value.quote.price) || value.quote.price <= 0 || !value.quote.currency)) throw new Error("종목 시세 또는 통화가 일치하지 않습니다.");
  for (const row of value.financials) {
    if (!["annual", "quarterly", "semiannual"].includes(row.type) || !/^\d{4}-\d{2}-\d{2}$/.test(row.period_end) || !Number.isFinite(Date.parse(row.period_end)) || new Date(row.period_end).toISOString().slice(0,10) !== row.period_end || row.period_end > new Date().toISOString().slice(0,10) || !row.currency) throw new Error("실적 기간 또는 통화를 확인할 수 없습니다.");
    for (const key of ["revenue", "operating_income", "net_income", "total_assets", "total_debt", "operating_cash_flow", "free_cash_flow"] as const) if (row[key] != null && !Number.isFinite(row[key])) throw new Error("재무 수치를 확인할 수 없습니다.");
  }
  const profile = (companyProfiles as Record<string, NonNullable<StockInformation["company"]>>)[ticker.toUpperCase()];
  if (value.company?.number_of_employees == null && profile) return { ...value, company: { ...value.company, ...profile } };
  return value;
}
export async function decodePublishedInformation(response: Response): Promise<unknown> {
  const bytes = await response.arrayBuffer();
  const magic = new Uint8Array(bytes, 0, Math.min(2, bytes.byteLength));
  const body = magic[0] === 0x1f && magic[1] === 0x8b
    ? await new Response(new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip"))).text()
    : new TextDecoder().decode(bytes);
  return JSON.parse(body);
}
export async function getStockInformation(ticker: string, exchange?: string, signal?: AbortSignal, fromSource = false): Promise<StockInformation> {
  const key = ticker.toUpperCase();
  let value = snapshots.get(key);
  if (fromSource) {
    const response = await requestOriginal<{items: StockInformation[]}>({kind: "information", stocks: [{ticker: key, ...(exchange ? {exchange} : {})}]}, signal);
    value = mergeInformation(value, validate(response.items[0], key));
  } else if (!value || Date.now() - (checkedAt.get(key) ?? 0) >= 60000) {
    const filename = encodeURIComponent(key).replaceAll("%", "~");
    let response = await fetchDataAsset(`${import.meta.env.BASE_URL}data/stock-information/${filename}.json.gz`, {signal, cache: "no-cache"});
    if (response.status === 404) response = await fetchDataAsset(`${import.meta.env.BASE_URL}data/stock-information/${filename}.json`, {signal, cache: "no-cache"});
    if (!response.ok) {
      if (!value) throw new Error("저장된 종목 정보를 불러오지 못했습니다. ‘정보 다시 조회’로 원본을 조회해 주세요.");
    } else {
      const remote = validate(await decodePublishedInformation(response) as StockInformation, key);
      if (!value || Date.parse(remote.fetched_at) >= Date.parse(value.fetched_at)) value = mergeInformation(value, remote);
    }
  }
  if (!value) throw new Error("종목 정보를 확인할 수 없습니다.");
  snapshots.set(key, value);
  checkedAt.set(key, Date.now());
  if (value.quote) rememberInformationQuote(value.quote);
  return value;
}
