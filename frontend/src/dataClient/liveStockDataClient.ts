import type { QuoteSnapshot, SiteIndex, StockSummary } from "./types";
import type { SemiconductorData, SemiconductorFinancial, SemiconductorPrice, RecentFinancials } from "./semiconductorTypes";
import type { NewHighIndex, NewHighReport } from "./newHighTypes";
import type { TurnoverIndex, TurnoverReport } from "./turnoverTypes";

export interface LiveQuote {
  ticker: string; price: number; previous_close: number | null; change: number | null; change_pct: number | null;
  currency: string; source: string; fetched_at: string; provider_time: string | null; market_time: string | null;
  status: "ok" | "stale"; provider_date?: string; name?: string; market_cap?: number | null; market_cap_currency?: string; market_cap_usd?: number; metrics?: Record<string, string | null>; warnings?: string[];
}
export interface LiveDetail {
  ticker: string; quote: LiveQuote; fetched_at: string; warnings: string[]; history?: SemiconductorPrice[];
  metrics?: Record<string, string | null>; annual_financials?: SemiconductorFinancial[]; quarterly_financials?: SemiconductorFinancial[]; recent_financials?: RecentFinancials;
}
export interface SourceMetadata { source_fetched_at?: string; refresh_warning?: string }
interface BatchResult<T> { fetched_at: string; items: T[]; errors: { ticker: string; message: string }[] }
export type StockRequest = { ticker: string; exchange?: string };
type Report = NewHighReport | TurnoverReport;
const API_BASE = import.meta.env.VITE_LIVE_API_URL || "https://find-peer-stock-live-api.find-peer-stock-juyeop.workers.dev";
const quotes = new Map<string, LiveQuote>();
const details = new Map<string, LiveDetail>();
const reports = new Map<string, Report & SourceMetadata>();
export function sourceMetadata(value: unknown): SourceMetadata {
  if (!value || typeof value !== "object") return {};
  const metadata = value as SourceMetadata;
  return { source_fetched_at: metadata.source_fetched_at, refresh_warning: metadata.refresh_warning };
}
export const liveQuoteFor = (ticker: string) => quotes.get(ticker.toUpperCase());
export function rememberInformationQuote(quote: LiveQuote) {
  const key = quote.ticker.toUpperCase(), old = quotes.get(key);
  if (old && quote.status === "stale" && Date.parse(quote.provider_time ?? quote.provider_date ?? quote.fetched_at) < Date.parse(old.provider_time ?? old.provider_date ?? old.market_time ?? old.fetched_at)) return;
  if (!old || Date.parse(quote.fetched_at) >= Date.parse(old.fetched_at)) quotes.set(key, { ...old, ...quote });
}
export const liveDetailFor = (ticker: string) => details.get(ticker.toUpperCase());
export function livePriceLabel(ticker: string): string | null {
  const quote = liveQuoteFor(ticker);
  return quote ? `${new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 4 }).format(quote.price)} ${quote.currency}` : null;
}
export function liveReportFor(kind: string, market: string, date?: string) {
  const result = reports.get(`${kind}:${market}`);
  return result && (!date || result.date === date) ? result : null;
}
export async function requestOriginal<T>(body: object, signal?: AbortSignal): Promise<T> {
  const controller = new AbortController();
  const abort = () => controller.abort();
  if (signal?.aborted) abort();
  signal?.addEventListener("abort", abort, { once: true });
  const timer = window.setTimeout(abort, 90_000);
  try {
    const response = await fetch(`${API_BASE.replace(/\/$/, "")}/refresh`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), cache: "no-store", signal: controller.signal });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error ?? "원본 제공처에서 최신 값을 가져오지 못했습니다. 기존 값은 유지됩니다.");
    return payload as T;
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new Error(error instanceof Error && error.name !== "AbortError" ? error.message : "원본 조회가 지연되고 있습니다. 기존 값은 유지됩니다. 다시 시도해 주세요.");
  } finally { window.clearTimeout(timer); signal?.removeEventListener("abort", abort); }
}
async function batches<T>(kind: "quotes" | "details", stocks: StockRequest[], signal?: AbortSignal): Promise<BatchResult<T>> {
  const unique = [...new Map(stocks.map(stock => [stock.ticker.toUpperCase(), { ticker: stock.ticker.toUpperCase(), ...(stock.exchange ? { exchange: stock.exchange } : {}) }])).values()];
  if (!unique.length) throw new Error("조회할 종목이 없습니다.");
  // A two-year chart per invocation stays within the Workers Free CPU budget.
  const size = kind === "details" ? 1 : 12;
  const chunks = Array.from({ length: Math.ceil(unique.length / size) }, (_, i) => unique.slice(i * size, (i + 1) * size));
  const result: BatchResult<T> = { fetched_at: "", items: [], errors: [] };
  let cursor = 0;
  await Promise.all(Array.from({ length: Math.min(4, chunks.length) }, async () => {
    while (cursor < chunks.length) {
      if (signal?.aborted) throw new DOMException("Aborted", "AbortError");
      const chunk = chunks[cursor++];
      try {
        const response = await requestOriginal<BatchResult<T>>({ kind, stocks: chunk }, signal);
        result.items.push(...response.items); result.errors.push(...response.errors);
        if (response.fetched_at > result.fetched_at) result.fetched_at = response.fetched_at;
      } catch (error) {
        if (signal?.aborted) throw error;
        result.errors.push(...chunk.map(stock => ({ ticker: stock.ticker, message: error instanceof Error ? error.message : "조회 실패" })));
      }
    }
  }));
  if (!result.items.length) throw new Error(result.errors[0]?.message ?? "원본 조회에 실패했습니다. 기존 값은 유지됩니다.");
  return result;
}
function metadata(result: BatchResult<unknown>): SourceMetadata {
  return { source_fetched_at: result.fetched_at, refresh_warning: result.errors.length ? `${result.errors.length}종목의 원본 조회에 실패해 기존 값을 유지했습니다. ${result.errors.slice(0, 3).map(error => error.ticker).join(", ")}` : undefined };
}
export async function refreshQuotes(stocks: StockRequest[], signal?: AbortSignal): Promise<SourceMetadata> {
  const result = await batches<LiveQuote>("quotes", stocks, signal);
  for (const quote of result.items) {
    const key = quote.ticker.toUpperCase();
    quotes.set(key, { ...quotes.get(key), ...quote });
  }
  const partial = result.items.filter(item => item.warnings?.length);
  return { ...metadata(result), refresh_warning: partial.length ? `${partial.length}종목의 일부 지표를 가져오지 못했습니다. 해당 지표는 기존 값을 유지합니다.${result.errors.length ? ` ${result.errors.length}종목의 현재가 조회도 실패했습니다.` : ""}` : metadata(result).refresh_warning };
}
export async function refreshDetails(stocks: StockRequest[], signal?: AbortSignal): Promise<SourceMetadata> {
  const result = await batches<LiveDetail>("details", stocks, signal);
  for (const detail of result.items) {
    const key = detail.ticker.toUpperCase();
    const previous = details.get(key);
    details.set(key, { ...previous, ...detail, ...(detail.metrics ? { metrics: { ...previous?.metrics, ...detail.metrics } } : {}) });
    quotes.set(key, { ...quotes.get(key), ...detail.quote });
  }
  const partial = result.items.filter(item => item.warnings.length);
  return { ...metadata(result), refresh_warning: result.errors.length || partial.length ? `${result.errors.length + partial.length}종목에서 일부 원본 자료를 가져오지 못했습니다. 해당 항목은 기존 값을 유지합니다.` : undefined };
}
export function applyQuote(base: QuoteSnapshot): QuoteSnapshot {
  const fresh = liveQuoteFor(base.ticker);
  if (fresh?.status === "stale" && Date.parse(fresh.provider_time ?? fresh.provider_date ?? fresh.fetched_at) < Date.parse(base.provider_time ?? base.provider_date ?? base.market_time ?? base.fetched_at)) return base;
  return fresh && Date.parse(fresh.fetched_at) >= Date.parse(base.fetched_at) ? { ...base, ...fresh, error: null, refresh_status: "fetched" } : base;
}
export function applySummary(base: StockSummary): StockSummary {
  return { ...base, quote: applyQuote(base.quote), peer_groups: base.peer_groups.map(group => ({ ...group, peers: group.peers.map(peer => ({ ...peer, quote: applyQuote(peer.quote) })) })) };
}
export function applyIndex(base: SiteIndex): SiteIndex {
  return { ...base, stocks: base.stocks.map(stock => {
    const fresh = liveQuoteFor(stock.ticker);
    return fresh && Date.parse(fresh.fetched_at) >= Date.parse(base.generated_at) && fresh.market_cap ? { ...stock, market_cap: fresh.market_cap, market_cap_currency: fresh.market_cap_currency, ...(fresh.market_cap_usd ? { market_cap_usd: fresh.market_cap_usd } : {}) } : stock;
  }) };
}
export function applySemiconductor(base: SemiconductorData): SemiconductorData {
  return { ...base, stocks: base.stocks.map(stock => {
    const quote = liveQuoteFor(stock.ticker), detail = liveDetailFor(stock.ticker);
    const recent = detail && Date.parse(detail.fetched_at) >= Date.parse(base.generated_at) ? detail : null;
    return { ...stock, ...(recent?.history ? { history: recent.history } : {}), ...(recent?.metrics ? { metrics: { ...stock.metrics, ...recent.metrics } } : {}),
      ...(recent?.annual_financials ? { annual_financials: recent.annual_financials } : {}), ...(recent?.quarterly_financials ? { quarterly_financials: recent.quarterly_financials } : {}),
      ...(recent?.recent_financials ? { recent_financials: recent.recent_financials } : {}), quote: quote && quote.fetched_at >= stock.quote.fetched_at ? { ...stock.quote, ...quote } : stock.quote };
  }) };
}
export async function refreshScan(kind: "new-highs" | "turnover", market: string, signal?: AbortSignal): Promise<Report & SourceMetadata> {
  const fresh = await requestOriginal<Report & { live_fetched_at: string }>({ kind: "scan", market, source: kind }, signal);
  if (fresh.market !== market || !Array.isArray(fresh.entries)) throw new Error("원본 조회 결과의 시장이 일치하지 않습니다.");
  const result = { ...fresh, source_fetched_at: fresh.live_fetched_at };
  reports.set(`${kind}:${market}`, result);
  return result;
}
export function applyHighIndex(base: NewHighIndex, market: string): NewHighIndex {
  const fresh = liveReportFor("new-highs", market) as NewHighReport & SourceMetadata | null;
  if (!fresh) return base;
  const count = (entries: NewHighReport["entries"]) => ({ total: entries.length, high_52_week: entries.filter(entry => entry.high_type === "52_week").length, high_all_time: entries.filter(entry => entry.high_type === "all_time").length });
  return { ...base, ...sourceMetadata(fresh), reports: [...base.reports.filter(report => report.market !== market || report.date !== fresh.date),
    { market, date: fresh.date, counts: count(fresh.entries), exchanges: Object.fromEntries((base.markets.find(item => item.id === market)?.exchanges ?? []).map(exchange => [exchange.id, count(fresh.entries.filter(entry => entry.exchange === exchange.id))])) }] };
}
export function applyTurnoverIndex(base: TurnoverIndex, market: string): TurnoverIndex {
  const fresh = liveReportFor("turnover", market) as TurnoverReport & SourceMetadata | null;
  if (!fresh) return base;
  return { ...base, ...sourceMetadata(fresh), reports: [...base.reports.filter(report => report.market !== market || report.date !== fresh.date),
    { market, date: fresh.date, count: fresh.entries.length, total_turnover: fresh.entries.reduce((sum, entry) => sum + entry.turnover, 0), currency: fresh.entries[0]?.turnover_currency ?? fresh.entries[0]?.currency ?? null }] };
}
