import type { SiteIndex, StockSummary } from "./types";
import type { NewHighIndex, NewHighReport } from "./newHighTypes";
import type { TurnoverIndex, TurnoverReport } from "./turnoverTypes";
import type { SemiconductorData } from "./semiconductorTypes";
import type { CreditData } from "./creditTypes";
import type { CalendarHistory, HistoryKind } from "./calendarHistory";
import { applyHighIndex, applyIndex, applySemiconductor, applySummary, applyTurnoverIndex, liveDetailFor, liveQuoteFor, liveReportFor, refreshDetails, refreshQuotes, refreshScan, requestOriginal } from "./liveStockDataClient";
import { refreshStockHistory } from "./stockHistoryClient";
import { getStockInformation } from "./stockInformationClient";
let refreshedCredit: CreditData | null = null;

function assetUrl(path: string): string {
  const cleanBase = import.meta.env.BASE_URL.replace(/\/$/, "");
  const cleanPath = path.replace(/^\//, "");
  return `${cleanBase}/${cleanPath}?t=${Date.now()}`;
}

async function fetchJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const controller = new AbortController();
  const abort = () => controller.abort();
  if (signal?.aborted) abort();
  signal?.addEventListener("abort", abort, { once: true });
  let timedOut = false;
  const timeout = window.setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, 20_000);

  try {
    const response = await fetch(assetUrl(path), {
      cache: "no-store",
      signal: controller.signal,
      headers: { Accept: "application/json" }
    });
    if (!response.ok) {
      throw new Error(`데이터를 불러오지 못했습니다. (${response.status})`);
    }
    return await response.json() as T;
  } catch (error: unknown) {
    if (timedOut) throw new Error("데이터 응답이 지연되고 있습니다. 잠시 후 자동으로 다시 확인합니다.");
    throw error;
  } finally {
    window.clearTimeout(timeout);
    signal?.removeEventListener("abort", abort);
  }
}

export async function getSiteIndex(signal?: AbortSignal, fromSource = false, current?: SiteIndex | null): Promise<SiteIndex> {
  const base = fromSource && current ? current : await fetchJson<SiteIndex>("data/index.json", signal);
  const metadata = fromSource ? await refreshQuotes(base.stocks.filter(stock => stock.is_target), signal) : {};
  return { ...applyIndex(base), ...metadata };
}

export async function getStockSummary(ticker: string, signal?: AbortSignal, fromSource = false, current?: StockSummary | null): Promise<StockSummary> {
  const base = fromSource && current ? current : await fetchJson<StockSummary>(`data/stocks/${encodeURIComponent(ticker)}.json`, signal);
  if (!fromSource) await getStockInformation(ticker, undefined, signal).catch(error => { if (signal?.aborted) throw error; });
  const metadata = fromSource ? await refreshQuotes([{ ticker }, ...base.peer_groups.flatMap(group => group.peers.map(peer => ({ ticker: peer.company.ticker })))], signal) : {};
  if (fromSource) {
    try { await getStockInformation(ticker, undefined, signal, true); }
    catch (error) {
      if (signal?.aborted) throw error;
      Object.assign(metadata, {refresh_warning: "일부 기업 정보·실적 조회에 실패해 이전 자료를 유지합니다."});
    }
    try { await refreshStockHistory(ticker, undefined, signal); }
    catch (error) {
      if (signal?.aborted) throw error;
      Object.assign(metadata, { refresh_warning: `${"refresh_warning" in metadata && metadata.refresh_warning ? metadata.refresh_warning + " " : ""}일봉 조회에 실패해 이전 차트를 유지합니다.` });
    }
  }
  return { ...applySummary(base), ...metadata };
}

export async function getNewHighIndex(signal?: AbortSignal, fromSource = false, current?: NewHighIndex | null, market?: string): Promise<NewHighIndex> {
  const base = fromSource && current ? current : await fetchJson<NewHighIndex>("data/new-highs/index.json", signal);
  const scope = base.markets.some(item => item.id === market) ? market! : "korea";
  if (fromSource) await refreshScan("new-highs", scope, signal);
  return market ? applyHighIndex(base, scope) : base;
}

export async function getNewHighReport(market: string, date: string, signal?: AbortSignal, fromSource = false): Promise<NewHighReport> {
  const base = liveReportFor("new-highs", market, date) as NewHighReport | null ?? await fetchJson<NewHighReport>(
    `data/new-highs/${encodeURIComponent(market)}/${encodeURIComponent(date)}.json`, signal
  );
  const metadata = fromSource && base.entries.length ? await refreshQuotes(base.entries, signal) : {};
  return { ...base, entries: base.entries.map(entry => ({ ...entry, name: liveQuoteFor(entry.ticker)?.name ?? entry.name })), ...metadata };
}

export async function getTurnoverIndex(signal?: AbortSignal, fromSource = false, current?: TurnoverIndex | null, market?: string): Promise<TurnoverIndex> {
  const base = fromSource && current ? current : await fetchJson<TurnoverIndex>("data/turnover/index.json", signal);
  const scope = base.markets.some(item => item.id === market) ? market! : "korea";
  if (fromSource) await refreshScan("turnover", scope, signal);
  return market ? applyTurnoverIndex(base, scope) : base;
}

export async function getTurnoverReport(market: string, date: string, signal?: AbortSignal, fromSource = false): Promise<TurnoverReport> {
  const month = date.slice(0, 7).replace("-", "_");
  const base = liveReportFor("turnover", market, date) as TurnoverReport | null ?? await fetchJson<TurnoverReport>(
    `data/turnover/${encodeURIComponent(market)}/${month}/${encodeURIComponent(date)}.json`, signal
  );
  const metadata = fromSource && base.entries.length ? await refreshQuotes(base.entries, signal) : {};
  return { ...base, entries: base.entries.map(entry => ({ ...entry, name: liveQuoteFor(entry.ticker)?.name ?? entry.name })), ...metadata };
}

export async function getSemiconductorData(signal?: AbortSignal, fromSource = false, current?: SemiconductorData | null, tickers?: string[]): Promise<SemiconductorData> {
  const base = fromSource && current ? current : await fetchJson<SemiconductorData>("data/semiconductor/index.json", signal);
  const metadata = fromSource ? await refreshDetails(base.stocks.filter(stock => !tickers || tickers.includes(stock.ticker)), signal) : {};
  if (fromSource && tickers?.length === 1) {
    try { await getStockInformation(tickers[0], undefined, signal, true); }
    catch (error) { if (signal?.aborted) throw error; Object.assign(metadata, {refresh_warning: "일부 기업 정보·실적 조회에 실패해 이전 자료를 유지합니다."}); }
  }
  return { ...applySemiconductor(base), ...metadata };
}

export async function getCreditData(signal?: AbortSignal, fromSource = false, current?: CreditData | null): Promise<CreditData> {
  const base = fromSource && current ? current : await fetchJson<CreditData>("data/credit/index.json", signal);
  if (!fromSource) return refreshedCredit && refreshedCredit.latest_date >= base.latest_date ? refreshedCredit : base;
  const fresh = await requestOriginal<{ fetched_at: string; history: CreditData["history"] }>({ kind: "credit" }, signal);
  const byDate = new Map([...base.history, ...fresh.history].map(point => [point.date, point]));
  const history = [...byDate.values()].sort((a, b) => a.date.localeCompare(b.date));
  refreshedCredit = { ...base, history, latest_date: history.at(-1)!.date, source_fetched_at: fresh.fetched_at } as CreditData;
  return refreshedCredit;
}

export async function getCalendarHistory(kind: HistoryKind, market: string, year: string, signal?: AbortSignal): Promise<CalendarHistory> {
  return fetchJson<CalendarHistory>(`data/${kind}/history/${encodeURIComponent(market)}/${encodeURIComponent(year)}.json`, signal);
}

export interface CalendarStockPrices {
  market: string;
  ticker: string;
  history: { date: string; close: number; currency: string }[];
}

export async function getCalendarStockPrices(market: string, ticker: string, signal?: AbortSignal): Promise<CalendarStockPrices> {
  const fresh = liveDetailFor(ticker);
  if (fresh?.history) return { market, ticker, history: fresh.history.map(point => ({ ...point, currency: fresh.quote.currency })) };
  const filename = encodeURIComponent(ticker).replaceAll("%", "~");
  return fetchJson<CalendarStockPrices>(`data/calendar-stocks/${encodeURIComponent(market)}/${filename}.json`, signal);
}
