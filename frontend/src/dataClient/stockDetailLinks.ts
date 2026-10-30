import semiconductorSeeds from "../../../data/seed/semiconductor_stocks.json";

export type CalendarSource = "new-highs" | "turnover";
const semiconductorTickers = new Set(semiconductorSeeds.map((stock) => stock.ticker));

export function calendarStockLink(ticker: string, source: CalendarSource, market: string, date: string, returnTo: string): string {
  const normalized = ticker.trim().toUpperCase();
  const query = new URLSearchParams({ source, market, date, returnTo });
  const base = semiconductorTickers.has(normalized) ? "semiconductors" : "market-stocks";
  return `/${base}/${encodeURIComponent(normalized)}?${query}`;
}

export function calendarReturnLink(value: string | null, fallback = "/new-highs"): string {
  return value && /^\/(new-highs|turnover|calendar-history|sectors|sector-stocks|sector-trends)(?:\?|$)/.test(value) ? value : fallback;
}

export function tradingViewSymbol(ticker: string, exchange = ""): string | null {
  const normalized = ticker.trim().toUpperCase();
  const exchanges: Record<string, string> = {
    KRX: "KRX", KOSPI: "KRX", KOSDAQ: "KRX", NASDAQ: "NASDAQ", NYSE: "NYSE", AMEX: "AMEX", HKEX: "HKEX",
    SSE: "SSE", SZSE: "SZSE", TWSE: "TWSE", TPEX: "TPEX", TSE: "TSE",
    EURONEXT: "EURONEXT", XETRA: "XETR", XETR: "XETR", LSE: "LSE", SIX: "SIX",
  };
  const suffixes: Record<string, string> = { KS: "KRX", KQ: "KRX", T: "TSE", TW: "TWSE", TWO: "TPEX", SS: "SSE", SZ: "SZSE", DE: "XETR", L: "LSE", SW: "SIX", PA: "EURONEXT", AS: "EURONEXT", BR: "EURONEXT" };
  const prefix = exchange ? exchanges[exchange.toUpperCase()] : normalized.includes(":") ? exchanges[normalized.split(":")[0]] : normalized.endsWith(".HK") ? "HKEX" : suffixes[normalized.split(".").at(-1)!];
  if (!prefix) return null;
  const explicit = normalized.split(":");
  if (explicit.length > 2 || (explicit.length === 2 && (exchanges[explicit[0]] ?? explicit[0]) !== prefix)) return null;
  let symbol = explicit.at(-1)!;
  if (explicit.length === 1) symbol = symbol.replace(/\.(KS|KQ|TWO|TW|T|SS|SZ|PA|AS|BR|DE|L|SW|HK)$/, "");
  if (prefix === "HKEX" && /^\d+$/.test(symbol)) symbol = String(Number(symbol));
  if (["NASDAQ", "NYSE", "AMEX"].includes(prefix)) symbol = symbol.replaceAll("-", ".");
  return /^[A-Z0-9][A-Z0-9.\-]*$/.test(symbol) ? `${prefix}:${symbol}` : null;
}

export function tradingViewUrl(symbol: string): string {
  return `https://www.tradingview.com/symbols/${encodeURIComponent(symbol.replace(":", "-"))}/`;
}
