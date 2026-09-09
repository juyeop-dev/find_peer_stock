import type { SiteIndex, StockSummary } from "./types";
import type { NewHighIndex, NewHighReport } from "./newHighTypes";

function assetUrl(path: string, cacheBust = false): string {
  const cleanBase = import.meta.env.BASE_URL.replace(/\/$/, "");
  const cleanPath = path.replace(/^\//, "");
  const query = cacheBust ? `?t=${Date.now()}` : "";
  return `${cleanBase}/${cleanPath}${query}`;
}

async function fetchJson<T>(path: string, cacheBust = false): Promise<T> {
  const response = await fetch(assetUrl(path, cacheBust), {
    cache: cacheBust ? "no-store" : "default",
    headers: {
      Accept: "application/json"
    }
  });

  if (!response.ok) {
    throw new Error(`데이터를 불러오지 못했습니다. (${response.status})`);
  }

  return response.json() as Promise<T>;
}

export async function getSiteIndex(cacheBust = false): Promise<SiteIndex> {
  return fetchJson<SiteIndex>("data/index.json", cacheBust);
}

export async function getStockSummary(ticker: string, cacheBust = false): Promise<StockSummary> {
  return fetchJson<StockSummary>(`data/stocks/${encodeURIComponent(ticker)}.json`, cacheBust);
}

export async function getNewHighIndex(): Promise<NewHighIndex> {
  return fetchJson<NewHighIndex>("data/new-highs/index.json", true);
}

export async function getNewHighReport(market: string, date: string): Promise<NewHighReport> {
  return fetchJson<NewHighReport>(
    `data/new-highs/${encodeURIComponent(market)}/${encodeURIComponent(date)}.json`, true
  );
}
