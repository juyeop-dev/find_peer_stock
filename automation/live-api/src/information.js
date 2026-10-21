import { jsonSource, numeric, tvSymbol, yahooSymbol } from "./providers.js";

const START = "2024-07-01";
const fields = { revenue: "TotalRevenue", operating_income: "OperatingIncome", net_income: "NetIncome", total_assets: "TotalAssets", total_debt: "TotalDebt", operating_cash_flow: "OperatingCashFlow", free_cash_flow: "FreeCashFlow" };
export function reportedFinancials(payload, symbol, today) {
  if (payload.timeseries?.error) throw new Error("확정 실적 조회 실패");
  const rows = new Map();
  for (const series of payload.timeseries?.result ?? []) {
    if (series.meta?.symbol?.length !== 1 || series.meta.symbol[0] !== symbol) throw new Error("실적 종목이 일치하지 않습니다.");
    for (const type of ["annual", "quarterly"]) for (const [metric, field] of Object.entries(fields)) {
      for (const item of series[type + field] ?? []) {
        const day = item.asOfDate, currency = item.currencyCode, value = numeric(item.reportedValue?.raw);
        if (!/^\d{4}-\d{2}-\d{2}$/.test(day ?? "") || day < START || day > today || !currency || value === null || item.periodType !== (type === "annual" ? "12M" : "3M")) continue;
        const key = `${type}:${day}:${currency}`;
        const row = rows.get(key) ?? { type, period_end: day, currency, source: "Yahoo Finance reported financials" };
        row[metric] = value; rows.set(key, row);
      }
    }
  }
  return [...rows.values()];
}
export function naverStatements(payload, type, today) {
  const info = payload.financeInfo ?? {};
  const metrics = Object.fromEntries((info.rowList ?? []).map(row => [row.title, row.columns ?? {}]));
  return (info.trTitleList ?? []).filter(period => period.isConsensus === "N" && /^\d{6}$/.test(period.key)).flatMap(period => {
    const year = Number(period.key.slice(0, 4)), month = Number(period.key.slice(4));
    if (month < 1 || month > 12) return [];
    const day = new Date(Date.UTC(year, month, 0)).toISOString().slice(0, 10);
    if (day < START || day > today) return [];
    const row = { type, period_end: day, currency: "KRW", source: "Naver Finance reported financials" };
    for (const [metric, title] of [["revenue", "매출액"], ["operating_income", "영업이익"], ["net_income", "당기순이익"]]) {
      const value = numeric(metrics[title]?.[period.key]?.value); row[metric] = value === null ? null : value * 1e8;
    }
    return [row.revenue, row.operating_income, row.net_income].some(value => value !== null) ? [row] : [];
  });
}

async function scanner(stock, today, fetcher) {
  let candidates = [tvSymbol(stock.ticker, stock.exchange)];
  if (stock.ticker.endsWith(".HK")) candidates = [`HKEX:${Number(stock.ticker.split(".")[0])}`];
  if (!candidates[0].includes(":")) candidates = ["NASDAQ", "NYSE", "AMEX"].map(exchange => `${exchange}:${stock.ticker}`);
  const columns = ["description", "sector", "industry", "number_of_employees", "close", "change", "currency", "time", "market_cap_basic", "fundamental_currency_code", "price_earnings_ttm", "price_book_fq", "earnings_per_share_diluted_ttm", "dividends_yield_current", "price_52_week_high", "price_52_week_low", ...["fy", "fq", "fh"].flatMap(period => ["fiscal_period_end", "total_revenue", "oper_income", "net_income"].map(field => `${field}_${period}`))];
  const response = await jsonSource("https://scanner.tradingview.com/global/scan", { symbols: { tickers: candidates }, columns, price_conversion: { to_symbol: true } }, fetcher);
  if (response.data?.length !== 1 || !candidates.includes(response.data[0].s) || response.data[0].d?.length !== columns.length) throw new Error("같은 거래소의 종목 정보를 확인할 수 없습니다.");
  const row = Object.fromEntries(columns.map((field, index) => [field, response.data[0].d[index]]));
  let usdCap = row.fundamental_currency_code === "USD" ? numeric(row.market_cap_basic) : null;
  if (usdCap === null && row.fundamental_currency_code !== "USD") {
    try {
      const caps = await jsonSource("https://scanner.tradingview.com/global/scan", {symbols: {tickers: [response.data[0].s]}, columns: ["market_cap_basic", "fundamental_currency_code"]}, fetcher);
      if (caps.data?.length === 1 && caps.data[0].s === response.data[0].s && caps.data[0].d?.[1] === "USD") usdCap = numeric(caps.data[0].d[0]);
    } catch { /* The native-currency capitalization remains independently valid. */ }
  }
  const fetched_at = new Date().toISOString();
  const result = { ticker: stock.ticker, requested_start: START, fetched_at, source_symbol: response.data[0].s, quote: null,
    company: Object.fromEntries(["description", "sector", "industry", "number_of_employees"].map(key => [key, row[key]])),
    metrics_currency: row.fundamental_currency_code, metrics: Object.fromEntries([["per", "price_earnings_ttm"], ["pbr", "price_book_fq"], ["eps", "earnings_per_share_diluted_ttm"], ["dividend_yield", "dividends_yield_current"], ["high_52_week", "price_52_week_high"], ["low_52_week", "price_52_week_low"]].map(([key, field]) => [key, numeric(row[field])])), financials: [] };
  const price = numeric(row.close), ratio = numeric(row.change), timestamp = numeric(row.time);
  if (price > 0 && row.currency && timestamp > 0 && timestamp * 1000 <= Date.now() + 86400000) {
    const previous = ratio !== null && ratio > -100 ? price / (1 + ratio / 100) : null;
    result.quote = { ticker: stock.ticker, price, previous_close: previous, change: previous === null ? null : price - previous, change_pct: ratio, currency: row.currency,
      source: "TradingView stock scanner", fetched_at, provider_time: new Date(timestamp * 1000).toISOString(), market_time: null, status: "ok", market_cap: numeric(row.market_cap_basic), market_cap_currency: row.fundamental_currency_code,
      ...(usdCap !== null ? { market_cap_usd: usdCap } : {}) };
    if (Date.now() - timestamp * 1000 > 7 * 86400000) result.quote.status = "stale";
  }
  for (const [type, suffix] of [["annual", "fy"], ["quarterly", "fq"], ["semiannual", "fh"]]) {
    const timestamp = numeric(row[`fiscal_period_end_${suffix}`]);
    if (!timestamp || !row.fundamental_currency_code) continue;
    const day = new Date(timestamp * 1000).toISOString().slice(0, 10);
    if (day < START || day > today) continue;
    const financial = { type, period_end: day, currency: row.fundamental_currency_code, source: "TradingView reported financials", revenue: numeric(row[`total_revenue_${suffix}`]), operating_income: numeric(row[`oper_income_${suffix}`]), net_income: numeric(row[`net_income_${suffix}`]) };
    if ([financial.revenue, financial.operating_income, financial.net_income].some(value => value !== null)) result.financials.push(financial);
  }
  return result;
}

export async function information(stock, fetcher = fetch) {
  const today = new Date().toISOString().slice(0, 10), warnings = [];
  const safe = async (label, operation) => { try { return await operation(); } catch { warnings.push(`${label} 조회 실패`); return null; } };
  const yahooStatements = async (end, quarterlyOnly = false) => {
    const symbol = yahooSymbol(stock.ticker);
    if (!symbol) return [];
    const types = (quarterlyOnly ? ["quarterly"] : ["annual", "quarterly"]).flatMap(prefix => Object.values(fields).map(field => prefix + field));
    const query = new URLSearchParams({type: types.join(","), period1: "1719792000", period2: String(end)});
    return reportedFinancials(await jsonSource(`https://query1.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/${encodeURIComponent(symbol)}?${query}`, undefined, fetcher), symbol, today);
  };
  const financials = async () => {
    let latest;
    if (/^\d{6}\.(KS|KQ)$/.test(stock.ticker)) {
      const code = stock.ticker.slice(0, 6);
      latest = (await Promise.all([["annual", "annual"], ["quarterly", "quarter"]].map(async ([type, path]) => await safe(`${type === "annual" ? "연간" : "분기"} 실적`, async () => naverStatements(await jsonSource(`https://m.stock.naver.com/api/stock/${code}/finance/${path}`, undefined, fetcher), type, today)) ?? []))).flat();
    } else {
      latest = await safe("최근 확정 실적", () => yahooStatements(Math.floor(Date.now() / 1000))) ?? [];
    }
    const older = await safe("2025년 과거 분기 실적", () => yahooStatements(1767225600, true)) ?? [];
    const historical = await safe("2024년 하반기 확정 실적", () => yahooStatements(1735689600)) ?? [];
    const keys = new Set(latest.map(row => `${row.type}:${row.period_end}`));
    const merged = [...latest];
    for (const row of [...older, ...historical]) {
      const key = `${row.type}:${row.period_end}`;
      if (!keys.has(key)) { merged.push(row); keys.add(key); }
      else if (row.period_end < "2025-01-01") {
        const index = merged.findIndex(item => `${item.type}:${item.period_end}` === key);
        const previous = merged[index];
        // Prefer one complete native report, without splicing fields from
        // different providers or reporting currencies into the same row.
        const metrics = Object.keys(fields);
        if (previous.currency === row.currency && metrics.every(metric => previous[metric] == null || row[metric] != null)
          && metrics.filter(metric => row[metric] != null).length > metrics.filter(metric => previous[metric] != null).length) merged[index] = row;
      }
    }
    return merged;
  };
  const [snapshot, statements] = await Promise.all([safe("기업 정보·투자 지표", () => scanner(stock, today, fetcher)), safe("과거 확정 실적", financials)]);
  if (!snapshot && !statements?.length) throw new Error("종목 원본 정보를 확인하지 못했습니다.");
  const result = snapshot ?? {ticker: stock.ticker, requested_start: START, fetched_at: new Date().toISOString(), quote: null, metrics: {}, financials: []};
  const keys = new Set((statements ?? []).map(row => `${row.type}:${row.period_end}`));
  result.financials = [...result.financials.filter(row => !keys.has(`${row.type}:${row.period_end}`)), ...(statements ?? [])].sort((a, b) => a.period_end.localeCompare(b.period_end) || a.type.localeCompare(b.type));
  if (!result.financials.length) warnings.push("2024년 하반기 이후 확정 실적이 제공되지 않습니다.");
  if (result.quote?.status === "stale") warnings.push("제공처에 최근 7일 이내 거래 자료가 없어 이전 제공 가격을 표시합니다.");
  const dates = result.financials.map(row => row.period_end).sort();
  const historical = result.financials.filter(row => row.period_end >= START && row.period_end <= "2024-12-31");
  return { ...result, warnings, financials_fetched_at: new Date().toISOString(),
    historical_2024_h2_coverage: {start: START, end: "2024-12-31", periods: historical.length, annual_periods: historical.filter(row => row.type === "annual").length, quarterly_periods: historical.filter(row => row.type === "quarterly").length, note: "확인된 확정 실적만 표시합니다. 연간 실적은 해당 회계연도 전체이며, 미제공 분기는 추정하지 않습니다."},
    financial_coverage: { first_period: dates[0] ?? null, latest_period: dates.at(-1) ?? null, note: "제공된 확정 회계기간만 표시합니다. 제공처가 제한한 과거 분기와 공시되지 않은 기간은 채우지 않습니다." } };
}
