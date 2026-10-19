import { jsonSource, localDay, numeric } from "./providers.js";

export const SECTOR_COLUMNS = ["name", "description", "exchange", "type", "subtype", "sector", "industry", "close", "change", "Value.Traded", "market_cap_basic", "currency", "time", "indexes", "Perf.W", "Perf.1M", "Perf.3M", "Perf.Y"];
export const sectorScanBody = () => ({
  columns: SECTOR_COLUMNS,
  filter: [{ left: "type", operation: "equal", right: "stock" }, { left: "subtype", operation: "equal", right: "common" }],
  options: { lang: "ko", price_conversion: { to_symbol: true } },
  range: [0, 6000],
});
const nonnegative = value => { const n = numeric(value); return n !== null && n >= 0 ? n : null; };

export function sectorSnapshot(payload, now = new Date()) {
  if (!Array.isArray(payload?.data) || !Number.isInteger(payload.totalCount) || payload.totalCount < 1 || payload.data.length !== payload.totalCount) {
    throw new Error("국내 전체 종목 조회가 완결되지 않았습니다.");
  }
  const stocks = [], seen = new Set();
  const excluded = { unsupported_listing: 0, missing_price: 0, other_currency: 0 };
  for (const item of payload.data) {
    if (!Array.isArray(item?.d) || item.d.length !== SECTOR_COLUMNS.length) throw new Error("업종 원본의 열 구성이 일치하지 않습니다.");
    const row = Object.fromEntries(SECTOR_COLUMNS.map((key, i) => [key, item.d[i]]));
    if (row.exchange !== "KRX" || row.type !== "stock" || row.subtype !== "common" || !/^[0-9A-Z]{6}$/.test(row.name ?? "") || item.s !== `KRX:${row.name}`) {
      excluded.unsupported_listing++; continue;
    }
    const indexes = Array.isArray(row.indexes) ? row.indexes : [];
    const boards = ["KOSPI", "KOSDAQ"].filter(board => indexes.some(index => index?.proname === `KRX:${board}`));
    if (boards.length > 1) throw new Error("종목의 시장 구분이 서로 충돌합니다.");
    if (!boards.length) { excluded.unsupported_listing++; continue; }
    if (row.currency !== "KRW") { excluded.other_currency++; continue; }
    const price = numeric(row.close), time = numeric(row.time);
    if (!(price > 0) || !(time > 0)) { excluded.missing_price++; continue; }
    if (seen.has(item.s)) throw new Error("중복 종목이 반환됐습니다.");
    seen.add(item.s);
    const date = localDay(time * 1000, "Asia/Seoul");
    if (date > localDay(now.getTime(), "Asia/Seoul")) throw new Error("미래 거래일이 반환됐습니다.");
    const change = numeric(row.change);
    stocks.push({
      ticker: `${row.name}.${boards[0] === "KOSPI" ? "KS" : "KQ"}`, code: row.name,
      name: typeof row.description === "string" && row.description.trim() ? row.description.replace(/보통주$/, "").trim() : row.name,
      exchange: boards[0], sector: typeof row.sector === "string" && row.sector.trim() ? row.sector : "Unclassified",
      industry: typeof row.industry === "string" && row.industry.trim() ? row.industry : "Unclassified",
      currency: "KRW", price, change_pct: change, turnover: nonnegative(row["Value.Traded"]), market_cap: nonnegative(row.market_cap_basic), date,
      returns: { day: change, week: numeric(row["Perf.W"]), month: numeric(row["Perf.1M"]), quarter: numeric(row["Perf.3M"]), year: numeric(row["Perf.Y"]) },
    });
  }
  if (!stocks.length) throw new Error("집계할 국내 보통주가 없습니다.");
  const date = stocks.reduce((latest, stock) => stock.date > latest ? stock.date : latest, "");
  stocks.sort((a, b) => a.ticker.localeCompare(b.ticker));
  return {
    schema_version: 1, market: "korea", currency: "KRW", date, fetched_at: now.toISOString(),
    source: "TradingView", source_url: "https://kr.tradingview.com/markets/stocks-korea/sectorandindustry-industry/",
    universe: "KOSPI·KOSDAQ 보통주 · ETF·우선주·KONEX 제외", received: payload.totalCount, excluded,
    stale_count: stocks.filter(stock => stock.date !== date).length, stocks,
  };
}

export async function sectors(fetcher = fetch) {
  return sectorSnapshot(await jsonSource("https://scanner.tradingview.com/korea/scan", sectorScanBody(), fetcher));
}
