import type { QuoteSnapshot } from "./types";

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
