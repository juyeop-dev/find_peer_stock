export interface ReplayBar {
  date: string; close: number; adjusted_close: number; volume: number | null;
  open?: number; high?: number; low?: number;
}
export interface ReplayMarket {
  ticker: string; name: string; currency: string; source: string; bars: ReplayBar[];
}
export interface ReplaySelection { ticker: string; name: string; exchange?: string; start: string; end: string }
export type ReplayInterval = "day" | "week" | "month";
export const REPLAY_PRESET: ReplaySelection[] = [
  { ticker: "^KS11", name: "코스피", start: "2022-01-01", end: "2022-12-31" },
  { ticker: "GC=F", name: "금 선물 (연속)", start: "2024-01-01", end: "2024-12-31" },
];

export interface ReplaySettings {
  selections: ReplaySelection[]; overlay: boolean; kind: "line" | "candles"; interval: ReplayInterval;
  average: boolean; volume: boolean; logarithmic: boolean; count: number | null; speed: number;
  autoPeer: boolean; peerReason?: string;
}
export function initialReplaySettings(ticker?: string, name?: string, exchange?: string, now = new Date()): ReplaySettings {
  const selections = REPLAY_PRESET.map(row => ({ ...row }));
  if (ticker) {
    const end = new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Seoul" }).format(now);
    const [year, month, day] = end.split("-").map(Number);
    const start = new Date(Date.UTC(year - 1, month - 1, Math.min(day, new Date(Date.UTC(year - 1, month, 0)).getUTCDate()))).toISOString().slice(0, 10);
    selections[0] = { ticker, name: name ?? ticker, exchange, start, end };
    selections[1] = { ticker: "", name: "비교 종목 선택", start, end };
  }
  return { selections, overlay: Boolean(ticker), kind: ticker ? "line" : "candles", interval: "day", average: false, volume: false, logarithmic: false, count: ticker ? null : 25, speed: 2, autoPeer: Boolean(ticker) };
}
export function restoreReplaySettings(raw: string | null, fallback: ReplaySettings, stockContext = false): ReplaySettings {
  try {
    const saved = JSON.parse(raw ?? "null");
    if (!saved || ![1, 2].includes(saved.version) || saved.selections?.length !== 2 || !saved.selections.every((row: ReplaySelection) => typeof row.ticker === "string" && /^[A-Z0-9^][A-Z0-9.^:_=\-]{0,39}$/.test(row.ticker) && typeof row.name === "string" && row.name.length < 150 && (row.exchange === undefined || typeof row.exchange === "string") && validReplayDate(row.start) && validReplayDate(row.end) && row.start <= row.end)) return fallback;
    const oldDefault = stockContext && saved.version === 1 && saved.selections[1].ticker === REPLAY_PRESET[1].ticker
      && saved.selections[1].start === REPLAY_PRESET[1].start && saved.selections[1].end === REPLAY_PRESET[1].end;
    const selections = saved.selections.map((row: ReplaySelection, i: number) => oldDefault && i === 1
      ? { ...fallback.selections[1], start: saved.selections[0].start, end: saved.selections[0].end } : row);
    return { ...fallback, selections, overlay: stockContext && saved.version === 1 ? true : saved.overlay === true,
      kind: saved.kind === "candles" ? "candles" : "line", interval: ["day", "week", "month"].includes(saved.interval) ? saved.interval : "day",
      average: saved.average === true, volume: saved.volume === true, logarithmic: saved.logarithmic === true,
      count: oldDefault || saved.count === null ? null : Number.isInteger(saved.count) && saved.count > 0 && saved.count < 100000 ? saved.count : fallback.count,
      speed: [1, 2, 5, 10].includes(saved.speed) ? saved.speed : 2, autoPeer: oldDefault || saved.version === 2 && saved.autoPeer === true,
      peerReason: typeof saved.peerReason === "string" ? saved.peerReason.slice(0, 250) : undefined };
  } catch { return fallback; }
}

export function validReplayDate(value: string): boolean {
  return /^\d{4}-\d{2}-\d{2}$/.test(value) && Number.isFinite(Date.parse(value)) && new Date(value).toISOString().slice(0, 10) === value;
}
export function validateReplayMarket(value: ReplayMarket): ReplayMarket {
  if (!value || typeof value.ticker !== "string" || !value.ticker || typeof value.currency !== "string" || !value.currency || typeof value.source !== "string" || !Array.isArray(value.bars) || !value.bars.length) throw new Error("차트 자료의 종목·출처를 확인할 수 없습니다.");
  let previous = "";
  for (const bar of value.bars) {
    if (!validReplayDate(bar.date) || bar.date <= previous || !Number.isFinite(bar.close) || bar.close <= 0 || !Number.isFinite(bar.adjusted_close) || bar.adjusted_close <= 0) throw new Error("차트 날짜 또는 가격이 올바르지 않습니다.");
    if ([bar.open, bar.high, bar.low].some(v => v !== undefined) && (!hasOHLC(bar) || bar.low! > Math.min(bar.open!, bar.close) || bar.high! < Math.max(bar.open!, bar.close) || bar.high! < bar.low!)) throw new Error("시가·고가·저가 자료가 올바르지 않습니다.");
    if (bar.volume !== null && (!Number.isFinite(bar.volume) || bar.volume < 0)) throw new Error("거래량 자료가 올바르지 않습니다.");
    previous = bar.date;
  }
  return value;
}
export function hasOHLC(bar: ReplayBar): boolean {
  return [bar.open, bar.high, bar.low].every(v => typeof v === "number" && Number.isFinite(v) && v > 0);
}
export function replayRange(bars: ReplayBar[], start: string, end: string): ReplayBar[] {
  if (!validReplayDate(start) || !validReplayDate(end) || start > end) throw new Error("시작일과 종료일을 확인해 주세요.");
  return bars.filter(bar => bar.date >= start && bar.date <= end);
}
// Aggregate only the bars already revealed by replay. A weekly/monthly bar
// must never contain a high, low, close or volume from a hidden future day.
export function aggregateReplay(bars: ReplayBar[], interval: ReplayInterval): ReplayBar[] {
  if (interval === "day") return bars;
  const groups = new Map<string, ReplayBar[]>();
  for (const bar of bars) {
    const day = new Date(`${bar.date}T12:00:00Z`);
    if (interval === "week") day.setUTCDate(day.getUTCDate() - (day.getUTCDay() + 6) % 7);
    const key = interval === "month" ? bar.date.slice(0, 7) : day.toISOString().slice(0, 10);
    const rows = groups.get(key) ?? []; rows.push(bar); groups.set(key, rows);
  }
  return [...groups.values()].map(rows => {
    const first = rows[0], last = rows.at(-1)!;
    return { date: first.date, close: last.close, adjusted_close: last.adjusted_close,
      volume: rows.every(b => b.volume !== null) ? rows.reduce((sum, b) => sum + b.volume!, 0) : null,
      ...(rows.every(hasOHLC) ? { open: first.open, high: Math.max(...rows.map(b => b.high!)), low: Math.min(...rows.map(b => b.low!)) } : {}) };
  });
}
export function replayReturns(bars: ReplayBar[]) {
  const base = bars[0]?.adjusted_close;
  return bars.map((bar, index) => ({ session: index + 1, date: bar.date, value: (bar.adjusted_close / base - 1) * 100 }));
}
export function replayAverage(bars: ReplayBar[], length: number) {
  const values: { date: string; value: number }[] = [];
  let sum = 0;
  for (let i = 0; i < bars.length; i++) {
    sum += bars[i].close;
    if (i >= length) sum -= bars[i - length].close;
    if (i >= length - 1) values.push({ date: bars[i].date, value: sum / length });
  }
  return values;
}
