export interface ChartSymbol { ticker: string; name: string; exchange?: string; market?: string }
let catalog: Promise<ChartSymbol[]> | undefined;
export function getChartSymbols(): Promise<ChartSymbol[]> {
  if (!catalog) catalog = (async () => {
    const response = await fetch(`${import.meta.env.BASE_URL}data/chart-catalog.json.gz`);
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
