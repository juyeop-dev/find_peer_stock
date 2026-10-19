import { localDay, numeric, tvSymbol, yahooData, yahooSymbol } from "./providers.js";

const encode = (method, params) => {
  const body = JSON.stringify({ m: method, p: params });
  return `~m~${body.length}~m~${body}`;
};
export function decodeFrames(frame) {
  const messages = [];
  while (frame) {
    const match = frame.match(/^~m~(\d+)~m~/);
    if (!match) throw new Error("차트 메시지 형식을 확인할 수 없습니다.");
    const length = Number(match[1]), start = match[0].length;
    if (frame.length < start + length) throw new Error("차트 메시지가 불완전합니다.");
    messages.push(frame.slice(start, start + length)); frame = frame.slice(start + length);
  }
  return messages;
}
export async function tradingViewHistory(stock, fetcher = fetch) {
  const symbol = tvSymbol(stock.ticker, stock.exchange);
  if (!symbol.includes(":")) throw new Error("정확한 거래소를 확인할 수 없습니다.");
  const response = await fetcher("https://data.tradingview.com/socket.io/websocket", {
    headers: { Upgrade: "websocket", Origin: "https://www.tradingview.com" }, signal: AbortSignal.timeout(18000),
  });
  const socket = response.webSocket;
  if (!socket) throw new Error("일봉 제공처에 연결하지 못했습니다.");
  socket.accept();
  return new Promise((resolve, reject) => {
    const session = `cs_${crypto.randomUUID().replaceAll("-", "").slice(0, 12)}`;
    let info = null, points = [], settled = false;
    const finish = (value, error) => {
      if (settled) return; settled = true; clearTimeout(timer);
      socket.close(1000, "history complete");
      error ? reject(error) : resolve(value);
    };
    const timer = setTimeout(() => finish(null, new Error("일봉 조회 시간이 초과됐습니다.")), 18000);
    socket.addEventListener("error", () => finish(null, new Error("일봉 연결 오류")));
    socket.addEventListener("close", () => { if (!settled) finish(null, new Error("일봉 수신 전에 연결이 종료됐습니다.")); });
    socket.addEventListener("message", event => {
      try {
        for (const body of decodeFrames(String(event.data))) {
          if (body.startsWith("~h~")) { socket.send(`~m~${body.length}~m~${body}`); continue; }
          const { m, p = [] } = JSON.parse(body);
          if (["critical_error", "protocol_error", "symbol_error", "series_error"].includes(m)) throw new Error("해당 거래소 종목의 일봉을 제공하지 않습니다.");
          if (p[0] !== session) continue;
          if (m === "symbol_resolved" && p[1] === "symbol_1") {
            info = p[2];
            if (info.pro_name !== symbol || info.source_id !== symbol.split(":")[0]
              || ["index", "forex", "crypto", "futures", "bond", "economic"].includes(info.type)) throw new Error("일봉 종목·거래소가 일치하지 않습니다.");
          } else if (m === "timescale_update") points.push(...(p[1]?.s1?.s ?? []));
          else if (m === "series_completed" && p[1] === "s1") {
            if (!info?.currency_code || !info.timezone) throw new Error("차트 종목 정보를 확인할 수 없습니다.");
            const days = new Map();
            for (const point of points) {
              const values = point.v;
              if (!Array.isArray(values) || !(numeric(values[0]) > 0) || !(numeric(values[4]) > 0)) throw new Error("일봉 가격 자료가 불완전합니다.");
              const day = localDay(values[0] * 1000, info.timezone);
              if (days.has(day)) throw new Error("중복 일봉이 포함돼 있습니다.");
              days.set(day, { date: day, close: values[4], adjusted_close: values[4], volume: numeric(values[5]) });
            }
            const history = [...days.values()].sort((a, b) => a.date.localeCompare(b.date));
            if (history.length < 2) throw new Error("표시할 일봉이 부족합니다.");
            finish({ ticker: stock.ticker, currency: info.currency_code, source: "TradingView split-adjusted daily chart",
              fetched_at: new Date().toISOString(), first_trade_date: null, history });
          }
        }
      } catch (error) { finish(null, error); }
    });
    socket.send(encode("set_auth_token", ["unauthorized_user_token"]));
    socket.send(encode("chart_create_session", [session, ""]));
    socket.send(encode("resolve_symbol", [session, "symbol_1", "=" + JSON.stringify({ symbol, adjustment: "splits", session: "regular" })]));
    socket.send(encode("create_series", [session, "s1", "s1", "symbol_1", "1D", 550]));
  });
}

export async function history(stock, fetcher = fetch) {
  try {
    const fresh = await yahooData(stock.ticker, fetcher, true);
    if (fresh.symbol !== yahooSymbol(stock.ticker) || !["EQUITY", "ETF", "MUTUALFUND"].includes(fresh.instrument_type)) throw new Error("일봉 종목이 일치하지 않습니다.");
    if (fresh.history.length < 2) throw new Error("표시할 일봉이 부족합니다.");
    return { ticker: stock.ticker, currency: fresh.quote.currency, source: "Yahoo Finance daily chart", fetched_at: fresh.quote.fetched_at,
      first_trade_date: fresh.first_trade_date, history: fresh.history };
  } catch { return tradingViewHistory(stock, fetcher); }
}
