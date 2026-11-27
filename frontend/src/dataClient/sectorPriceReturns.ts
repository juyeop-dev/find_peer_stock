import type { SectorPeriod, SectorSnapshot } from "./sectorRankings";

const DAY = 86400000;
const periods = ["day", "week", "month", "quarter", "year"] as const;
const emptyReturns = (): Record<SectorPeriod, number | null> => ({ day: null, week: null, month: null, quarter: null, year: null });
const isoDay = (date: Date) => date.toISOString().slice(0, 10);
const positive = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value) && value > 0;

export function returnReferenceDates(date: string) {
  const end = Date.parse(date);
  function monthsAgo(months: number) {
    const start = new Date(end);
    const day = start.getUTCDate();
    start.setUTCMonth(start.getUTCMonth() - months, 1);
    const lastDay = new Date(start.getTime());
    lastDay.setUTCMonth(lastDay.getUTCMonth() + 1, 0);
    start.setUTCDate(Math.min(day, lastDay.getUTCDate()));
    return isoDay(start);
  }
  return { day: isoDay(new Date(end - DAY)), week: isoDay(new Date(end - 7 * DAY)), month: monthsAgo(1), quarter: monthsAgo(3), year: monthsAgo(12) };
}

type PriceRow = [age: number, close: number] | null;
type Series = [ticker: string, primary: number | null, prior: number[], observed: number | null, quoteScale: number | null];
type PriceIndex = { version: number; key: string; revision: string; count: number; dates: string[]; tickers: Series[] };
type PriceDay = { key: string; date: string; rows: PriceRow[] };

function onOrBefore(dates: string[], date: string) {
  let first = 0, last = dates.length;
  while (first < last) {
    const middle = (first + last) >>> 1;
    if (dates[middle] <= date) first = middle + 1;
    else last = middle;
  }
  return dates[first - 1];
}

export function calculateSectorPriceReturns(snapshot: SectorSnapshot, index: PriceIndex, byDate: Map<string, PriceDay>, preferQuote: boolean): SectorSnapshot {
  const references = returnReferenceDates(snapshot.date);
  const anchors = periods.map(period => {
    const date = onOrBefore(index.dates, references[period]);
    return {period, rows: byDate.get(date)?.rows, elapsed: (Date.parse(references[period]) - Date.parse(date)) / DAY};
  });
  const end = byDate.get(snapshot.date);
  const sources = new Map(index.tickers.map(series => [series[0], series]));
  const hasQuotes = !snapshot.reconstruction && snapshot.source === "TradingView";
  const stocks = snapshot.stocks.map(stock => {
    const returns = emptyReturns();
    const series = sources.get(stock.ticker);
    if (series && stock.date === snapshot.date) {
      const [, primary, prior, observed, scale] = series;
      const closedCurves = [primary, ...prior].filter((id): id is number => id !== null && end?.rows[id]?.[0] === 0);
      const useQuote = hasQuotes && (preferQuote || (observed !== null && end?.rows[observed]?.[0] === 0));
      for (const {period, rows, elapsed} of anchors) {
        if (!rows) continue;
        const curve = closedCurves.find(id => rows[id]);
        const savedEnd = curve === undefined ? null : end?.rows[curve]?.[1];
        const savedBase = curve === undefined ? null : rows[curve]?.[1];
        const quoteBase = observed === null ? null : rows[observed];
        const quoteAge = quoteBase ? quoteBase[0] + elapsed : Infinity;
        // Allow holidays and weekends while keeping a stale quote from turning
        // into a much longer comparison than the chosen period.
        const quoteReturn = useQuote && quoteBase && quoteAge <= 7 ? stock.price / quoteBase[1] - 1 : null;
        const savedReturn = positive(savedEnd) && positive(savedBase) ? savedEnd / savedBase - 1 : null;
        const primaryBase = primary === null ? null : rows[primary]?.[1];
        const linkedReturn = useQuote && positive(scale) && positive(primaryBase) ? stock.price * scale / primaryBase - 1 : null;
        const result = preferQuote && quoteReturn !== null ? quoteReturn : savedReturn ?? quoteReturn ?? linkedReturn;
        if (result !== null && Number.isFinite(result)) returns[period] = result * 100;
      }
    }
    return { ...stock, change_pct: returns.day, returns };
  });
  return { ...snapshot, stocks };
}

async function readPriceDay(path: string, revision: string, signal?: AbortSignal): Promise<PriceDay> {
  const response = await fetch(`${path}?v=${revision}`, { cache: "force-cache", signal });
  if (!response.ok) throw new Error("저장된 종목 일봉을 불러오지 못했습니다.");
  const bytes = await response.arrayBuffer();
  const magic = new Uint8Array(bytes, 0, Math.min(2, bytes.byteLength));
  if (magic[0] === 0x1f && magic[1] === 0x8b) {
    return new Response(new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip"))).json();
  }
  return JSON.parse(new TextDecoder().decode(bytes));
}

export async function withSectorPriceReturns(snapshot: SectorSnapshot, preferQuote: boolean, signal?: AbortSignal): Promise<SectorSnapshot> {
  const root = `${import.meta.env.BASE_URL}data/stock-history/korea-daily/`;
  try {
    const response = await fetch(`${root}index.json`, { cache: "no-cache", signal });
    if (!response.ok) throw new Error("저장된 종목 일봉의 날짜 목록을 불러오지 못했습니다.");
    const index: PriceIndex = await response.json();
    if (index.version !== 1 || !/^[a-f0-9]{64}$/.test(index.revision) || !/^[a-f0-9]{64}$/.test(index.key)
      || !Number.isSafeInteger(index.count) || !Array.isArray(index.dates) || !Array.isArray(index.tickers)
      || index.dates.some((date, i) => !/^\d{4}-\d{2}-\d{2}$/.test(date) || i > 0 && date <= index.dates[i - 1])) {
      throw new Error("저장된 종목 일봉의 날짜 목록이 올바르지 않습니다.");
    }
    const dates = new Set(Object.values(returnReferenceDates(snapshot.date)).map(date => onOrBefore(index.dates, date)).filter(Boolean));
    if (onOrBefore(index.dates, snapshot.date) === snapshot.date) dates.add(snapshot.date);
    const byDate = new Map(await Promise.all([...dates].map(async date => {
      const value = await readPriceDay(`${root}${date}.json.gz`, index.revision, signal);
      if (value.date !== date || value.key !== index.key || !Array.isArray(value.rows) || value.rows.length !== index.count
        || value.rows.some(row => row !== null && (!Array.isArray(row) || !Number.isSafeInteger(row[0]) || row[0] < 0 || !positive(row[1])))) {
        throw new Error("저장된 종목 일봉의 가격 자료가 올바르지 않습니다.");
      }
      return [date, value] as const;
    })));
    return calculateSectorPriceReturns(snapshot, index, byDate, preferQuote);
  } catch (error) {
    if (signal?.aborted) throw error;
    return { ...snapshot, price_data_unavailable: true, stocks: snapshot.stocks.map(stock => ({ ...stock, change_pct: null, returns: emptyReturns() })) };
  }
}
