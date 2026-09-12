import type { SiteIndex, StockSummary } from "./types";
import type { NewHighIndex, NewHighReport } from "./newHighTypes";

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

export async function getSiteIndex(signal?: AbortSignal): Promise<SiteIndex> {
  return fetchJson<SiteIndex>("data/index.json", signal);
}

export async function getStockSummary(ticker: string, signal?: AbortSignal): Promise<StockSummary> {
  return fetchJson<StockSummary>(`data/stocks/${encodeURIComponent(ticker)}.json`, signal);
}

export async function getNewHighIndex(signal?: AbortSignal): Promise<NewHighIndex> {
  return fetchJson<NewHighIndex>("data/new-highs/index.json", signal);
}

export async function getNewHighReport(market: string, date: string, signal?: AbortSignal): Promise<NewHighReport> {
  return fetchJson<NewHighReport>(
    `data/new-highs/${encodeURIComponent(market)}/${encodeURIComponent(date)}.json`, signal
  );
}
