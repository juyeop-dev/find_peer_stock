import type { QuoteSnapshot } from "./types";

interface MarketCapFields {
  market_cap?: number | null;
  market_cap_currency?: string | null;
  market_cap_usd?: number | null;
}

export function quoteRefreshNotice(quote: QuoteSnapshot): string | null {
  if (quote.status === "stale" || (quote.refresh_status === "error" && quote.price !== null)) {
    return "최신 시세를 받지 못해 마지막으로 조회한 가격을 표시합니다.";
  }
  if (quote.status === "error") {
    return "시세를 불러오지 못했습니다. 다음 업데이트 때 다시 조회합니다.";
  }
  if (quote.refresh_status === "not_fetched") {
    return "이번 업데이트에서는 시세를 조회하지 않아 저장된 가격을 표시합니다.";
  }
  return null;
}

export function formatDateTime(value: string | null): string {
  if (!value) {
    return "-";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return new Intl.DateTimeFormat("ko-KR", {
    dateStyle: "medium",
    timeStyle: "medium",
    hour12: false
  }).format(date);
}

export function formatPrice(quote: QuoteSnapshot): string {
  if (quote.price === null) {
    return "-";
  }

  const maximumFractionDigits = quote.currency === "KRW" || quote.currency === "JPY" ? 0 : 2;
  return `${new Intl.NumberFormat("ko-KR", {
    maximumFractionDigits
  }).format(quote.price)} ${quote.currency}`;
}

export function formatMarketCap(value: MarketCapFields): string {
  if (value.market_cap === null || value.market_cap === undefined || !value.market_cap_currency) {
    return "-";
  }

  try {
    return new Intl.NumberFormat("ko-KR", {
      style: "currency",
      currency: value.market_cap_currency,
      notation: "compact",
      maximumFractionDigits: 2
    }).format(value.market_cap);
  } catch {
    return `${new Intl.NumberFormat("ko-KR", {
      notation: "compact",
      maximumFractionDigits: 2
    }).format(value.market_cap)} ${value.market_cap_currency}`;
  }
}

export function compareMarketCapDesc(left: MarketCapFields, right: MarketCapFields): number {
  const leftValue = validMarketCapUsd(left.market_cap_usd);
  const rightValue = validMarketCapUsd(right.market_cap_usd);
  if (leftValue === null && rightValue === null) {
    return 0;
  }
  if (leftValue === null) {
    return 1;
  }
  if (rightValue === null) {
    return -1;
  }
  return rightValue - leftValue;
}

function validMarketCapUsd(value: number | null | undefined): number | null {
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? value : null;
}

export function formatChange(quote: QuoteSnapshot): string {
  if (quote.change === null || quote.change_pct === null) {
    return "전일대비 -";
  }

  const sign = quote.change >= 0 ? "+" : "";
  const maximumFractionDigits = quote.currency === "KRW" || quote.currency === "JPY" ? 0 : 2;
  const change = new Intl.NumberFormat("ko-KR", {
    maximumFractionDigits
  }).format(quote.change);

  return `${sign}${change} ${quote.currency} (${sign}${quote.change_pct.toFixed(2)}%)`;
}

export function changeTone(quote: QuoteSnapshot): "up" | "down" | "flat" {
  if (quote.change_pct === null || quote.change_pct === 0) {
    return "flat";
  }

  return quote.change_pct > 0 ? "up" : "down";
}
