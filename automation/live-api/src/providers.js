const AGENT = "Mozilla/5.0 (compatible; StockPeerLive/1.0)";
export const MARKETS = {
  korea: ["korea", { KRX: "Asia/Seoul" }],
  us: ["america", { NASDAQ: "America/New_York", NYSE: "America/New_York", AMEX: "America/New_York" }],
  japan: ["japan", { TSE: "Asia/Tokyo" }],
  taiwan: ["taiwan", { TWSE: "Asia/Taipei", TPEX: "Asia/Taipei" }],
  china: ["china", { SSE: "Asia/Shanghai", SZSE: "Asia/Shanghai" }],
  europe: ["global", { EURONEXT: "Europe/Paris", XETR: "Europe/Berlin", LSE: "Europe/London", SIX: "Europe/Zurich" }],
};
export const numeric = value => {
  if (value === null || value === undefined || value === "" || typeof value === "boolean") return null;
  const result = Number(typeof value === "string" ? value.replaceAll(",", "").replace("%", "").trim() : value);
  return Number.isFinite(result) ? result : null;
};
export function wonAmount(value) {
  if (typeof value !== "string") return numeric(value);
  const units = { 조: 1e12, 억: 1e8, 만: 1e4 };
  const parts = [...value.matchAll(/([\d,.]+)\s*(조|억|만)/g)];
  return parts.length ? parts.reduce((sum, [, amount, unit]) => sum + Number(amount.replaceAll(",", "")) * units[unit], 0) : numeric(value);
}
const dayFormatters = new Map();
export function localDay(timestamp, timezone) {
  let formatter = dayFormatters.get(timezone);
  if (!formatter) {
    formatter = new Intl.DateTimeFormat("en", { timeZone: timezone, year: "numeric", month: "2-digit", day: "2-digit" });
    dayFormatters.set(timezone, formatter);
  }
  const parts = formatter.formatToParts(new Date(timestamp));
  return ["year", "month", "day"].map(type => parts.find(part => part.type === type)?.value).join("-");
}
export async function jsonSource(url, body, fetcher = fetch) {
  const endpoint = new URL(url);
  endpoint.searchParams.set("_refresh", String(Date.now()));
  const response = await fetcher(endpoint.href, {
    method: body === undefined ? "GET" : "POST", body: body === undefined ? undefined : JSON.stringify(body),
    headers: { "User-Agent": AGENT, Accept: "application/json", "Content-Type": "application/json", "Cache-Control": "no-cache", Pragma: "no-cache" },
    signal: AbortSignal.timeout(18_000), cf: { cacheTtl: 0, cacheEverything: false },
  });
  if (!response.ok) throw new Error(`원본 제공처 응답 오류 (${response.status})`);
  return response.json();
}
const naver = (code, path, fetcher) => jsonSource(`https://m.stock.naver.com/api/stock/${code}/${path}`, undefined, fetcher);
export async function koreanQuote(ticker, fetcher = fetch) {
  const code = ticker.split(".")[0];
  const [basic, integration] = await Promise.all([naver(code, "basic", fetcher), naver(code, "integration", fetcher).catch(() => null)]);
  const price = numeric(basic.closePrice), ratio = numeric(basic.fluctuationsRatio);
  if (!(price > 0)) throw new Error("Naver 현재가를 확인할 수 없습니다.");
  const rawChange = numeric(basic.compareToPreviousClosePrice);
  const change = rawChange === null ? null : ratio === null ? rawChange : Math.sign(ratio) * Math.abs(rawChange);
  const metrics = Object.fromEntries((integration?.totalInfos ?? []).map(item => [item.code, item.value]));
  return { ticker, price, previous_close: change === null ? null : price - change, change, change_pct: ratio,
    currency: "KRW", provider_time: basic.localTradedAt ?? null, market_time: basic.localTradedAt ?? null,
    market_status: basic.marketStatus === "OPEN" ? "open" : basic.marketStatus ? "closed" : null, name: basic.stockName, source: "Naver Finance · 직접 조회",
    fetched_at: new Date().toISOString(), status: "ok", metrics, warnings: integration ? [] : ["투자 지표 조회 실패"],
    ...(metrics.marketValue && wonAmount(metrics.marketValue) > 0 ? { market_cap: wonAmount(metrics.marketValue), market_cap_currency: "KRW" } : {}) };
}
export function yahooSymbol(ticker) {
  const [exchange, symbol] = ticker.split(":");
  if (symbol) {
    const suffix = { XETR: ".DE", XETRA: ".DE", LSE: ".L", SIX: ".SW" }[exchange];
    if (!suffix) return null; // EURONEXT spans several listings; do not guess a different listing.
    return symbol + suffix;
  }
  const normalized = ticker.replaceAll("/", "-");
  return /\.(KS|KQ|T|TW|TWO|SS|SZ|HK|DE|L|SW|PA|AS|BR|LS)$/.test(normalized) ? normalized : normalized.replaceAll(".", "-");
}
export async function yahooData(ticker, fetcher = fetch, history = false) {
  const symbol = yahooSymbol(ticker);
  if (!symbol) throw new Error("이 거래소는 TradingView에서 직접 조회합니다.");
  const payload = await jsonSource(`https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(symbol)}?range=${history ? "2y" : "5d"}&interval=1d&includePrePost=true`, undefined, fetcher);
  const result = payload.chart?.result?.[0];
  if (!result || payload.chart?.error) throw new Error("Yahoo Finance 가격 자료가 없습니다.");
  const meta = result.meta ?? {}, indicators = result.indicators ?? {};
  const closes = indicators.quote?.[0]?.close ?? [], adjusted = indicators.adjclose?.[0]?.adjclose ?? [];
  const volumes = indicators.quote?.[0]?.volume ?? [];
  const timezone = meta.exchangeTimezoneName ?? "UTC";
  const points = (result.timestamp ?? []).flatMap((time, i) => numeric(closes[i]) > 0 ? [{
    date: localDay(time * 1000, timezone), close: numeric(closes[i]), adjusted_close: numeric(adjusted[i]) ?? numeric(closes[i]), volume: numeric(volumes[i]),
  }] : []);
  const price = numeric(meta.regularMarketPrice) ?? points.at(-1)?.close;
  if (!(price > 0)) throw new Error("Yahoo Finance 현재가를 확인할 수 없습니다.");
  const day = meta.regularMarketTime ? localDay(meta.regularMarketTime * 1000, timezone) : points.at(-1)?.date;
  const previous = [...points].reverse().find(point => point.date < day)?.close ?? numeric(meta.previousClose);
  const timestamp = meta.regularMarketTime ? new Date(meta.regularMarketTime * 1000).toISOString() : null;
  return { symbol: meta.symbol, instrument_type: meta.instrumentType,
    first_trade_date: meta.firstTradeDate ? localDay(meta.firstTradeDate * 1000, timezone) : null,
    quote: { ticker, price, previous_close: previous ?? null, change: previous ? price - previous : null,
    change_pct: previous ? (price / previous - 1) * 100 : null, currency: meta.currency ?? "USD",
    provider_time: timestamp, market_time: timestamp, name: meta.longName ?? meta.shortName,
    exchange: ({ NMS: "NASDAQ", NGM: "NASDAQ", NCM: "NASDAQ", NYQ: "NYSE", ASE: "AMEX", PCX: "AMEX" })[meta.exchangeName],
    source: "Yahoo Finance · 직접 조회", fetched_at: new Date().toISOString(), status: "ok" }, history: points };
}
export function tvSymbol(ticker, exchange = "") {
  if (ticker.includes(":")) return ticker.replace(/^XETRA:/, "XETR:");
  const suffixes = { KS: "KRX", KQ: "KRX", T: "TSE", TW: "TWSE", TWO: "TPEX", SS: "SSE", SZ: "SZSE", DE: "XETR", PA: "EURONEXT", AS: "EURONEXT", BR: "EURONEXT", L: "LSE", SW: "SIX" };
  const match = ticker.match(/^(.*)\.([A-Z]+)$/);
  return match && suffixes[match[2]] ? `${suffixes[match[2]]}:${match[1]}` : exchange ? `${exchange}:${ticker.replaceAll("-", ".")}` : ticker;
}
export async function tradingViewQuote(ticker, exchange, fetcher = fetch) {
  const columns = ["close", "change", "currency", "market_cap_basic", "time", "description", "fundamental_currency_code"];
  const response = await jsonSource("https://scanner.tradingview.com/global/scan", { symbols: { tickers: [tvSymbol(ticker, exchange)] }, columns }, fetcher);
  const row = response.data?.[0]?.d;
  if (!row || !(numeric(row[0]) > 0)) throw new Error("TradingView 현재가를 확인할 수 없습니다.");
  const price = numeric(row[0]), ratio = numeric(row[1]);
  const previous = ratio !== null && ratio > -100 ? price / (1 + ratio / 100) : null;
  const time = numeric(row[4]) ? new Date(row[4] * 1000).toISOString() : null;
  return { ticker, price, previous_close: previous, change: previous === null ? null : price - previous, change_pct: ratio,
    currency: row[2], ...(numeric(row[3]) > 0 && /^[A-Z]{3}$/.test(row[6] ?? "") ? { market_cap: numeric(row[3]), market_cap_currency: row[6], ...(row[6] === "USD" ? { market_cap_usd: numeric(row[3]) } : {}) } : {}),
    provider_time: null, market_time: null, source_bar_time: time,
    name: row[5], source: "TradingView · 직접 조회", status: "ok", fetched_at: new Date().toISOString() };
}
export async function quote(stock, fetcher = fetch) {
  const addCap = async snapshot => {
    try {
      const cap = await tradingViewQuote(stock.ticker, stock.exchange ?? snapshot.exchange, fetcher);
      return { ...snapshot, ...(cap.market_cap_usd ? { market_cap_usd: cap.market_cap_usd } : {}),
        ...(!snapshot.market_cap && cap.market_cap ? { market_cap: cap.market_cap, market_cap_currency: cap.market_cap_currency, market_cap_source: "TradingView" } : {}) };
    } catch {
      return { ...snapshot, warnings: [...(snapshot.warnings ?? []), ...(!snapshot.market_cap ? ["시가총액 조회 실패"] : [])] };
    }
  };
  if (/^\d{6}\.(KS|KQ)$/.test(stock.ticker)) {
    try { return await addCap(await koreanQuote(stock.ticker, fetcher)); } catch { /* A second provider can still respond. */ }
  }
  try { return await addCap((await yahooData(stock.ticker, fetcher)).quote); }
  catch { return tradingViewQuote(stock.ticker, stock.exchange, fetcher); }
}
export function naverFinancialRows(payload, type) {
  const info = payload.financeInfo ?? {};
  const metrics = Object.fromEntries((info.rowList ?? []).map(row => [row.title, row.columns ?? {}]));
  return (info.trTitleList ?? []).filter(period => period.isConsensus === "N").flatMap(period => {
    const row = { period: period.title ?? period.key, type,
      revenue: numeric(metrics["매출액"]?.[period.key]?.value), operating_income: numeric(metrics["영업이익"]?.[period.key]?.value), net_income: numeric(metrics["당기순이익"]?.[period.key]?.value) };
    return [row.revenue, row.operating_income, row.net_income].some(value => value !== null) ? [row] : [];
  });
}
export function recentFinancials(quarterly, annual) {
  const quarters = new Map();
  for (const row of quarterly) {
    const match = row.period.match(/^(\d{4})\.(03|06|09|12)\.?$/);
    if (match) quarters.set(Number(match[1]) * 4 + Number(match[2]) / 3 - 1, row);
  }
  const last = Math.max(...quarters.keys());
  const indices = [last - 3, last - 2, last - 1, last];
  const label = index => `${Math.floor(index / 4)}년 ${index % 4 + 1}Q`;
  if (Number.isFinite(last) && indices.every(index => quarters.has(index))) {
    const rows = indices.map(index => quarters.get(index));
    const sum = key => rows.every(row => row[key] !== null) ? rows.reduce((total, row) => total + row[key], 0) : null;
    return { basis: "ttm", period_label: `${label(indices[0])}~${label(last)}`, periods: rows.map(row => row.period), latest_reported_period: rows.at(-1).period,
      revenue: sum("revenue"), operating_income: sum("operating_income"), reason: null };
  }
  const lastAnnual = [...annual].sort((a, b) => b.period.localeCompare(a.period))[0];
  if (lastAnnual) return { basis: "annual", period_label: `${lastAnnual.period} 결산 연간`, periods: [lastAnnual.period], latest_reported_period: quarters.get(last)?.period ?? null,
    revenue: lastAnnual.revenue, operating_income: lastAnnual.operating_income, reason: "연속 4개 분기 자료가 부족해 결산 연간 실적을 표시합니다." };
  return { basis: "unavailable", period_label: "자료 부족", periods: [], latest_reported_period: null, revenue: null, operating_income: null, reason: "확정 실적 자료를 확인할 수 없습니다." };
}
export async function detail(stock, fetcher = fetch) {
  const warnings = [];
  const safely = async (label, operation) => {
    try { return await operation(); } catch { warnings.push(`${label} 조회 실패`); return null; }
  };
  const korean = /^\d{6}\.(KS|KQ)$/.test(stock.ticker);
  const [freshQuote, chart, annual, quarter] = await Promise.all([
    safely("현재가", () => quote(stock, fetcher)), safely("일봉", () => yahooData(stock.ticker, fetcher, true)),
    korean ? safely("연간 실적", () => naver(stock.ticker.slice(0, 6), "finance/annual", fetcher)) : null,
    korean ? safely("분기 실적", () => naver(stock.ticker.slice(0, 6), "finance/quarter", fetcher)) : null,
  ]);
  if (!freshQuote && !chart) throw new Error("원본 제공처에서 이 종목의 최신 값을 가져오지 못했습니다.");
  warnings.push(...(freshQuote?.warnings ?? []));
  const result = { ticker: stock.ticker, quote: freshQuote ?? chart.quote, fetched_at: new Date().toISOString(), warnings };
  if (chart) result.history = chart.history;
  if (korean) {
    if (freshQuote?.metrics) result.metrics = freshQuote.metrics;
    if (annual) result.annual_financials = naverFinancialRows(annual, "annual");
    if (quarter) result.quarterly_financials = naverFinancialRows(quarter, "quarterly");
    if (annual && quarter) result.recent_financials = recentFinancials(result.quarterly_financials, result.annual_financials);
  }
  return result;
}

export async function credit(fetcher = fetch) {
  const day = localDay(Date.now(), "Asia/Seoul");
  const previous = new Date(`${day}T00:00:00Z`); previous.setUTCDate(1); previous.setUTCMonth(previous.getUTCMonth() - 1);
  const start = previous.toISOString().slice(0, 10).replaceAll("-", "");
  const response = await jsonSource("https://freesis.kofia.or.kr/meta/getMetaDataList.do", { dmSearch: {
    tmpV40: "1000000", tmpV41: "1", tmpV6: "2", tmpV7: "1", tmpV4: "", tmpV11: "", tmpV1: "RD", tmpV45: start,
    tmpV46: day.replaceAll("-", ""), OBJ_NM: "STATSCU0100000070BO",
  } }, fetcher);
  if (!Array.isArray(response.ds1)) throw new Error("금융투자협회 통계 응답을 확인할 수 없습니다.");
  const history = response.ds1.flatMap(row => {
    const date = String(row.TMPV1 ?? "");
    const [total, kospi, kosdaq] = [row.TMPV2, row.TMPV3, row.TMPV4].map(numeric);
    if (!/^\d{8}$/.test(date) || [total, kospi, kosdaq].some(value => value === null || value < 0) || Math.abs(total - kospi - kosdaq) > 1) return [];
    return [{ date: `${date.slice(0, 4)}-${date.slice(4, 6)}-${date.slice(6)}`, total, kospi, kosdaq }];
  }).sort((a, b) => a.date.localeCompare(b.date));
  if (!history.length) throw new Error("금융투자협회에서 최근 잔고 자료를 확인할 수 없습니다.");
  return { fetched_at: new Date().toISOString(), history };
}

export async function scan(market, kind, fetcher = fetch) {
  const [scanner, exchanges] = MARKETS[market];
  const columns = ["name", "description", "exchange", "type", "sector", "industry", "open", "high", "close", "change",
    "price_52_week_high", "High.All", "time", "currency", "market_cap_basic", "Value.Traded", "indexes", "fundamental_currency_code"];
  const rows = [];
  const scopes = market === "europe" ? Object.keys(exchanges).map(exchange => [exchange]) : [Object.keys(exchanges)];
  for (const scope of scopes) {
    // Filter at the provider before downloading rows to fit Workers Free CPU limits.
    // Query both thresholds so listings with missing 52-week fields remain eligible.
    for (const threshold of kind === "new-highs" ? ["price_52_week_high", "High.All"] : [null]) {
    let offset = 0;
    let total = 1;
    while (offset < total) {
      const payload = await jsonSource(`https://scanner.tradingview.com/${scanner}/scan`, {
        filter: [{ left: "type", operation: "equal", right: "stock" }, { left: "exchange", operation: "in_range", right: scope }, { left: "time", operation: "eless", right: Math.floor(Date.now() / 1000) },
          ...(threshold ? [{ left: "high", operation: "egreater", right: threshold }, { left: "change", operation: "egreater", right: 0 }, { left: "close", operation: "egreater", right: "open" }, { left: "volume", operation: "greater", right: 0 }] : [])],
        columns, sort: { sortBy: "Value.Traded", sortOrder: "desc" }, range: [offset, offset + (kind === "turnover" ? 60 : 500)],
      }, fetcher);
      if (!Array.isArray(payload.data) || !Number.isInteger(payload.totalCount)) throw new Error("종목 스캐너 응답을 확인할 수 없습니다.");
      total = payload.totalCount;
      if (total > 100000 || !payload.data.length && offset < total) throw new Error("종목 스캐너 자료가 불완전합니다.");
      for (const item of payload.data) {
        if (!Array.isArray(item.d) || item.d.length !== columns.length) throw new Error("종목 스캐너 행이 불완전합니다.");
        rows.push({ ...Object.fromEntries(columns.map((column, index) => [column, item.d[index]])), symbol: item.s });
      }
      offset += payload.data.length;
      if (kind === "turnover") break;
    }
    }
  }
  const uniqueRows = [...new Map(rows.map(row => [row.symbol, row])).values()];
  const sessionDays = new Map();
  const sessionDay = row => {
    const key = `${row.exchange}:${row.time}`;
    if (!sessionDays.has(key)) sessionDays.set(key, localDay(row.time * 1000, exchanges[row.exchange]));
    return sessionDays.get(key);
  };
  const latest = {};
  for (const row of uniqueRows) if (numeric(row.time) > 0 && exchanges[row.exchange]) {
    const day = sessionDay(row);
    latest[row.exchange] = [latest[row.exchange] ?? "", day].sort().at(-1);
  }
  let date = Object.values(latest).sort().at(-1);
  if (kind === "new-highs") {
    // Qualifying rows can be stale or empty: determine the actual session independently.
    const probe = await jsonSource(`https://scanner.tradingview.com/${scanner}/scan`, {
      filter: [{ left: "type", operation: "equal", right: "stock" }, { left: "exchange", operation: "in_range", right: Object.keys(exchanges) },
        { left: "volume", operation: "greater", right: 0 }, { left: "time", operation: "eless", right: Math.floor(Date.now() / 1000) }],
      columns: ["time", "exchange"], sort: { sortBy: "time", sortOrder: "desc" }, range: [0, 1],
    }, fetcher);
    const [time, exchange] = probe.data?.[0]?.d ?? [];
    if (!(numeric(time) > 0) || !exchanges[exchange]) throw new Error("거래일을 확인할 수 없습니다.");
    date = localDay(time * 1000, exchanges[exchange]);
  }
  if (!date) throw new Error("거래일을 확인할 수 없습니다.");
  let candidates = uniqueRows.filter(row => numeric(row.time) > 0 && numeric(row.close) > 0 && exchanges[row.exchange]
    && sessionDay(row) === date);
  if (kind === "new-highs") candidates = candidates.filter(row => numeric(row.change) !== null && row.change >= 0 && numeric(row.open) > 0 && row.close >= row.open
    && numeric(row.high) > 0 && (numeric(row["price_52_week_high"]) > 0 && row.high >= row["price_52_week_high"] || numeric(row["High.All"]) > 0 && row.high >= row["High.All"]));
  else candidates = candidates.filter(row => numeric(row["Value.Traded"]) > 0).sort((a, b) => b["Value.Traded"] - a["Value.Traded"]).slice(0, 30);
  const entries = [];
  let verified = 0;
  for (const row of candidates) {
    let exchange = row.exchange, name = row.description || row.name;
    if (market === "korea") {
      const memberships = new Set((Array.isArray(row.indexes) ? row.indexes : []).map(item => item.proname));
      exchange = memberships.has("KRX:KOSPI") ? "KOSPI" : memberships.has("KRX:KOSDAQ") ? "KOSDAQ" : null;
      if (!exchange) {
        if (++verified > 30) throw new Error("추가 종목의 국내 거래소를 확인하지 못했습니다. 기존 기록을 유지합니다.");
        const listing = await naver(row.name, "basic", fetcher);
        exchange = listing.stockExchangeType?.name ?? listing.stockExchangeName;
        name = listing.stockName || name;
      }
      if (!["KOSPI", "KOSDAQ"].includes(exchange)) continue;
    }
    const suffix = { KOSPI: ".KS", KOSDAQ: ".KQ", TSE: ".T", TWSE: ".TW", TPEX: ".TWO", SSE: ".SS", SZSE: ".SZ" }[exchange];
    const ticker = suffix ? row.name + suffix : market === "us" ? row.name : row.symbol;
    const category = row.sector || row.industry || "업종 미등록";
    const entry = { ticker, name, exchange, currency: row.currency, change_pct: numeric(row.change), market_cap: numeric(row.market_cap_basic), market_cap_currency: row.fundamental_currency_code ?? row.currency };
    if (kind === "new-highs") Object.assign(entry, { category, high_type: numeric(row["High.All"]) > 0 && row.high >= row["High.All"] ? "all_time" : "52_week",
      reason: `업종: ${category}`, description: row.industry || category, session_open: numeric(row.open), session_close: row.close });
    else Object.assign(entry, { rank: entries.length + 1, price: row.close, turnover: row["Value.Traded"], turnover_currency: market === "europe" ? "USD" : row.currency,
      sector: row.sector || "미등록", industry: row.industry || "미등록", source_symbol: row.symbol });
    entries.push(entry);
  }
  return { schema_version: 1, market, date, entries, live_fetched_at: new Date().toISOString(),
    summary: "원본 제공처에서 직접 조회한 최신 자료입니다. 장중에는 순위와 신고가 목록이 달라질 수 있습니다.",
    sources: [{ label: "TradingView · 직접 조회", url: "https://www.tradingview.com/screener/" }] };
}
