export const REBOUND_BOARDS = ["KOSPI", "KOSDAQ"] as const;
export type ReboundBoard = typeof REBOUND_BOARDS[number];
export const REBOUND_RULES = { KOSPI: { market_cap_min: 5e12, rebound_min: 8 }, KOSDAQ: { market_cap_min: 1e12, rebound_min: 5 } };
export interface ReboundEntry {
  ticker: string; name: string; exchange: ReboundBoard; currency: "KRW";
  price: number; low: number; change_pct: number; rebound_pct: number; market_cap: number;
  market_cap_currency: "KRW"; sector: string; industry: string;
}
export interface ReboundReport {
  schema_version: 1; market: "korea"; date: string; rules: typeof REBOUND_RULES; entries: ReboundEntry[];
  source_metadata: { provider: string; fetched_at: string; session: "daily"; scanned_symbols: number; excluded: Record<string, number>; note?: string };
  sources: { label: string; url: string }[];
}
export interface ReboundIndex {
  schema_version: 1; market: "korea"; rules: typeof REBOUND_RULES;
  reports: { date: string; count: number; counts: Partial<Record<ReboundBoard, number>>; fetched_at: string }[];
  closures: { date: string; reason: string }[];
  refresh: { status: string; message: string; target_date?: string; last_success_date?: string };
}
export function validReboundDate(value: unknown): value is string {
  return typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value) && Number.isFinite(Date.parse(value)) && new Date(value).toISOString().slice(0, 10) === value;
}
const signed = (value: number) => `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
export const reboundPercent = signed;
export const reboundPrice = (value: number) => `${value.toLocaleString("ko-KR", { maximumFractionDigits: 0 })}원`;
export function reboundDateLabel(value: string): string {
  const day = new Date(`${value}T00:00:00Z`);
  return `${value.replaceAll("-", ".")}(${["일", "월", "화", "수", "목", "금", "토"][day.getUTCDay()]})`;
}
export function validateReboundReport(value: ReboundReport, date: string): ReboundReport {
  if (!value || value.schema_version !== 1 || value.market !== "korea" || value.date !== date || !validReboundDate(date) || !Array.isArray(value.entries) || !Array.isArray(value.sources)) throw new Error("선택한 날짜의 반등 기록과 일치하지 않습니다.");
  if (!value.source_metadata || value.source_metadata.session !== "daily" || !Number.isFinite(Date.parse(value.source_metadata.fetched_at)) || !Number.isInteger(value.source_metadata.scanned_symbols) || value.source_metadata.scanned_symbols < 1 || REBOUND_BOARDS.some(board => value.rules?.[board]?.market_cap_min !== REBOUND_RULES[board].market_cap_min || value.rules?.[board]?.rebound_min !== REBOUND_RULES[board].rebound_min)) throw new Error("반등 보고서의 수집 정보 또는 선별 조건을 확인할 수 없습니다.");
  const seen = new Set<string>();
  for (const row of value.entries) {
    if (!row || !REBOUND_BOARDS.includes(row.exchange)) throw new Error("반등 종목의 시장을 확인할 수 없습니다.");
    const rule = REBOUND_RULES[row.exchange];
    if (!rule || !/^[0-9A-Z]{6}\.(KS|KQ)$/.test(row.ticker) || !row.ticker.endsWith(row.exchange === "KOSPI" ? ".KS" : ".KQ") || !row.name || row.currency !== "KRW" || row.market_cap_currency !== "KRW" || seen.has(row.ticker) || [row.price, row.low, row.change_pct, row.rebound_pct, row.market_cap].some(n => !Number.isFinite(n))) throw new Error("반등 종목의 시장·코드·수치를 확인할 수 없습니다.");
    const actual = (row.price / row.low - 1) * 100;
    if (!(row.low > 0 && row.low <= row.price) || row.change_pct < 0 || row.market_cap < rule.market_cap_min || actual + 1e-10 < rule.rebound_min || Math.abs(actual - row.rebound_pct) > 1e-8) throw new Error("반등 계산 또는 선별 조건이 일치하지 않습니다.");
    seen.add(row.ticker);
  }
  return value;
}
export function reboundEntries(report: ReboundReport, board: ReboundBoard, query = ""): ReboundEntry[] {
  const search = query.trim().toLocaleLowerCase();
  return report.entries.filter(row => row.exchange === board && `${row.name} ${row.ticker}`.toLocaleLowerCase().includes(search)).sort((a, b) => b.rebound_pct - a.rebound_pct || a.ticker.localeCompare(b.ticker));
}
export function reboundMessage(report: ReboundReport): string {
  const counts = REBOUND_BOARDS.map(board => `${board} ${reboundEntries(report, board).length}개 | 시총 ${board === "KOSPI" ? 5 : 1}조 이상 | 반등 ${REBOUND_RULES[board].rebound_min}% 이상`);
  return [`🇰🇷 ${reboundDateLabel(report.date)} 📊 국내 대형주 반등`, "(당일 저가 대비 종가 반등률)", "", ...counts, "전일 대비 하락 종목 제외", "─────────────────", ...REBOUND_BOARDS.flatMap(board => ["", `${board === "KOSPI" ? "🔵" : "🔴"} ${board} (${reboundEntries(report, board).length})`, "", ...reboundEntries(report, board).map(row => `• ${row.name} ${signed(row.rebound_pct)} | ${reboundPrice(row.price)} (${signed(row.change_pct)})`), ...(reboundEntries(report, board).length ? [] : ["조건에 맞는 종목이 없습니다."])])].join("\n");
}
async function request<T>(path: string, signal?: AbortSignal): Promise<T> {
  const timeout = AbortSignal.timeout(20000);
  const response = await fetch(`${import.meta.env.BASE_URL}data/rebounds/${path}?t=${Date.now()}`, { cache: "no-store", signal: signal ? AbortSignal.any([signal, timeout]) : timeout });
  if (!response.ok) throw new Error(`반등 기록을 불러오지 못했습니다. (${response.status})`);
  return response.json() as Promise<T>;
}
export async function getReboundIndex(signal?: AbortSignal): Promise<ReboundIndex> {
  const value = await request<ReboundIndex>("index.json", signal);
  if (value?.schema_version !== 1 || value.market !== "korea" || !Array.isArray(value.reports) || !Array.isArray(value.closures) || !value.refresh || value.reports.some(row => !validReboundDate(row.date) || !Number.isInteger(row.count) || row.count < 0)) throw new Error("반등 날짜 목록을 확인할 수 없습니다.");
  return value;
}
export async function getReboundReport(date: string, signal?: AbortSignal): Promise<ReboundReport> {
  if (!validReboundDate(date)) throw new Error("조회 날짜가 올바르지 않습니다.");
  return validateReboundReport(await request<ReboundReport>(`korea/${date.slice(0, 7).replace("-", "_")}/${date}.json`, signal), date);
}
