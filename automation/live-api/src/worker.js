import { MARKETS, credit, detail, quote, scan } from "./providers.js";
import { history } from "./history.js";

const validTicker = value => typeof value === "string" && value.length <= 48 && /^(?:[A-Z]+:)?[A-Z0-9][A-Z0-9.\-]*(?:\/[A-Z0-9.\-]+)?$/.test(value);
const validOrigin = (origin, env) => origin === (env.ALLOWED_ORIGIN ?? "https://juyeop-dev.github.io") || /^http:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/.test(origin);

export async function handle(request, env = {}, fetcher = fetch) {
  const origin = request.headers.get("Origin") ?? "";
  const headers = { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store, max-age=0", Vary: "Origin" };
  if (origin && validOrigin(origin, env)) Object.assign(headers, { "Access-Control-Allow-Origin": origin, "Access-Control-Allow-Methods": "POST, GET, OPTIONS", "Access-Control-Allow-Headers": "Content-Type", "Access-Control-Max-Age": "3600" });
  const response = (body, status = 200) => new Response(JSON.stringify(body), { status, headers });
  if (origin && !validOrigin(origin, env)) return response({ error: "허용되지 않은 사이트입니다." }, 403);
  if (request.method === "OPTIONS") return new Response(null, { status: 204, headers });
  const path = new URL(request.url).pathname;
  if (path === "/health" && request.method === "GET") return response({ status: "ok", version: 1 });
  if (path !== "/refresh" || request.method !== "POST") return response({ error: "지원하지 않는 요청입니다." }, 404);
  if (!request.headers.get("Content-Type")?.includes("application/json")) return response({ error: "JSON 요청이 필요합니다." }, 415);
  if (Number(request.headers.get("Content-Length")) > 30000) return response({ error: "요청이 너무 큽니다." }, 413);
  let body;
  try { const raw = await request.text(); if (raw.length > 30000) return response({ error: "요청이 너무 큽니다." }, 413); body = JSON.parse(raw); }
  catch { return response({ error: "요청을 읽을 수 없습니다." }, 400); }
  if (!body || typeof body !== "object") return response({ error: "요청을 확인해 주세요." }, 400);
  try {
    if (body.kind === "credit") return response(await credit(fetcher));
    if (body.kind === "scan") {
      if (!Object.hasOwn(MARKETS, body.market) || !["new-highs", "turnover"].includes(body.source)) return response({ error: "지원하는 시장과 자료 종류를 선택해 주세요." }, 400);
      return response(await scan(body.market, body.source, fetcher));
    }
    if (!["quotes", "details", "history"].includes(body.kind) || !Array.isArray(body.stocks) || !body.stocks.length || body.stocks.length > (body.kind === "history" ? 1 : body.kind === "details" ? 4 : 12)
      || body.stocks.some(stock => !stock || !validTicker(stock.ticker) || stock.exchange && !/^[A-Z]{2,12}$/.test(stock.exchange))) return response({ error: "종목 요청을 확인해 주세요." }, 400);
    const items = [], errors = [];
    // Keep each invocation below the free-plan subrequest limit, including fallbacks.
    const operation = body.kind === "history" ? history : body.kind === "details" ? detail : quote;
    for (let offset = 0; offset < body.stocks.length; offset += 3) {
      await Promise.all(body.stocks.slice(offset, offset + 3).map(async stock => {
        try { items.push(await operation(stock, fetcher)); } catch (error) {
          console.warn("live_provider_failure", String(error?.message ?? "unknown").replace(/https?:\/\/\S+/g, "[provider]"));
          errors.push({ ticker: stock.ticker, message: "원본 제공처에서 최신 값을 가져오지 못했습니다." });
        }
      }));
    }
    return response({ fetched_at: new Date().toISOString(), items, errors }, items.length ? 200 : 502);
  } catch (error) {
    console.warn("live_provider_failure", String(error?.message ?? "unknown").replace(/https?:\/\/\S+/g, "[provider]"));
    return response({ error: "원본 제공처 조회에 실패했습니다. 기존 값은 유지되며 잠시 후 다시 시도할 수 있습니다." }, 502);
  }
}

export default { fetch(request, env) { return handle(request, env); } };
