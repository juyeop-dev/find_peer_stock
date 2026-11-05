export interface ChartSymbol {
  ticker: string; name: string; exchange?: string; market?: string;
  sector?: string; industry?: string; business_groups?: string[]; peer_tickers?: string[];
  company_id?: string; market_cap_usd?: number; history_start?: string; history_end?: string;
}

const classification = (value?: string) => typeof value === "string" && !/^(unknown|unclassified|undefined|null|nan|n\/a|other|미분류|미등록)$/i.test(value.trim()) ? value.trim().toLocaleLowerCase() : "";
export function similarChartSymbols(rows: ChartSymbol[], ticker: string): { symbol: ChartSymbol; reason: string }[] {
  const base = rows.find(row => row.ticker.toUpperCase() === ticker.toUpperCase());
  if (!base) return [];
  const industry = classification(base.industry), sector = classification(base.sector);
  const groups = new Set(base.business_groups ?? []), peers = new Set(base.peer_tickers ?? []);
  const earliest = base.history_end ? Date.parse(base.history_end) - 90 * 86400000 : -Infinity;
  return rows.flatMap(symbol => {
    const koreanShare = /^[0-9A-Z]{6}\.(KS|KQ)$/.test(symbol.ticker);
    if (symbol.ticker.toUpperCase() === ticker.toUpperCase() || (base.company_id && symbol.company_id === base.company_id)
      || (koreanShare && (symbol.ticker[5] !== "0" || symbol.ticker.slice(0, 5) === base.ticker.slice(0, 5) && symbol.ticker.slice(-3) === base.ticker.slice(-3)))
      || symbol.ticker.startsWith("^") || symbol.ticker.includes("=") || (symbol.history_end && Date.parse(symbol.history_end) < earliest)) return [];
    const sameIndustry = Boolean(industry && classification(symbol.industry) === industry);
    const sameSector = Boolean(sector && classification(symbol.sector) === sector);
    const common = (symbol.business_groups ?? []).filter(group => groups.has(group));
    const linked = peers.has(symbol.ticker) || (symbol.peer_tickers ?? []).includes(base.ticker);
    if (!sameIndustry && !common.length && !linked) return [];
    const score = sameIndustry && common.length ? 6 : sameIndustry && linked ? 5 : common.length ? 4 : sameIndustry ? 3 : 2;
    const reason = common.length ? `같은 사업 분류 · ${common[0].split("/").at(-1)?.trim()}`
      : sameIndustry && linked ? `같은 세부 업종 · 등록된 피어 (${base.industry})`
      : sameIndustry ? `같은 세부 업종 · ${base.industry}` : "등록된 피어 관계";
    const capDistance = base.market_cap_usd && symbol.market_cap_usd && base.market_cap_usd > 0 && symbol.market_cap_usd > 0
      ? Math.abs(Math.log(symbol.market_cap_usd / base.market_cap_usd)) : Infinity;
    return [{ symbol, reason, score, common: common.length, sameSector, sameMarket: Boolean(base.market && base.market === symbol.market), capDistance }];
  }).sort((a, b) => b.score - a.score || b.common - a.common || Number(b.sameSector) - Number(a.sameSector)
    || Number(b.sameMarket) - Number(a.sameMarket) || a.capDistance - b.capDistance || a.symbol.ticker.localeCompare(b.symbol.ticker))
    .slice(0, 5).map(({ symbol, reason }) => ({ symbol, reason }));
}
let catalog: Promise<ChartSymbol[]> | undefined;
export function getChartSymbols(): Promise<ChartSymbol[]> {
  if (!catalog) catalog = (async () => {
    const response = await fetch(`${import.meta.env.BASE_URL}data/chart-catalog.json.gz?v=2`);
    if (!response.ok) throw new Error("종목 목록을 불러오지 못했습니다. 티커를 직접 입력할 수 있습니다.");
    const bytes = await response.arrayBuffer(), magic = new Uint8Array(bytes, 0, Math.min(2, bytes.byteLength));
    const text = magic[0] === 0x1f && magic[1] === 0x8b
      ? await new Response(new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip"))).text()
      : new TextDecoder().decode(bytes);
    const rows: ChartSymbol[] = JSON.parse(text);
    if (!Array.isArray(rows)) throw new Error("종목 목록의 형식이 올바르지 않습니다.");
    return rows.filter(row => typeof row.ticker === "string" && typeof row.name === "string");
  })().catch(error => { catalog = undefined; throw error; });
  return catalog;
}
export function searchChartSymbols(rows: ChartSymbol[], query: string, excluded: string[]): ChartSymbol[] {
  const text = query.trim().toLocaleLowerCase(), skip = new Set(excluded.map(t => t.toUpperCase()));
  if (!text) return [];
  return rows.filter(row => !skip.has(row.ticker.toUpperCase()) && `${row.ticker} ${row.name} ${row.exchange ?? ""}`.toLocaleLowerCase().includes(text))
    .sort((a, b) => Number(b.ticker.toLowerCase() === text) - Number(a.ticker.toLowerCase() === text)
      || Number(b.ticker.toLowerCase().startsWith(text)) - Number(a.ticker.toLowerCase().startsWith(text)) || a.ticker.localeCompare(b.ticker)).slice(0, 8);
}
