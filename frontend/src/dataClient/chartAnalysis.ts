import type { SemiconductorPrice } from "./semiconductorTypes";
import type { Anchor, PlotPoint } from "./chartWorkspace";

export const STUDIES = [
  { id: "ema20", name: "EMA 20", description: "20거래일 지수이동평균", group: "가격 지표" },
  { id: "ema60", name: "EMA 60", description: "60거래일 지수이동평균", group: "가격 지표" },
  { id: "bb", name: "볼린저 밴드", description: "20거래일 평균 ± 2 표준편차", group: "가격 지표" },
  { id: "rsi", name: "RSI", description: "14거래일 · Wilder 평활 · 30/70 기준선", group: "보조 지표" },
  { id: "macd", name: "MACD", description: "EMA 12 − EMA 26 · 시그널 9 · 히스토그램", group: "보조 지표" },
] as const;
export type StudyId = typeof STUDIES[number]["id"];
export interface AnalysisPreferences {
  studies: StudyId[]; averages: number[]; kind: "line" | "area"; grid: boolean; width: number; dashed: boolean;
}
export function parseAnalysisPreferences(raw: string | null): AnalysisPreferences {
  const defaults: AnalysisPreferences = { studies: [], averages: [], kind: "line", grid: true, width: 2, dashed: false };
  try {
    const value = JSON.parse(raw ?? "null");
    if (!value || typeof value !== "object") return defaults;
    return { studies: STUDIES.filter(s => Array.isArray(value.studies) && value.studies.includes(s.id)).map(s => s.id),
      averages: [20, 60, 120].filter(n => Array.isArray(value.averages) && value.averages.includes(n)),
      kind: value.kind === "area" ? "area" : "line", grid: value.grid !== false,
      width: [1, 2, 3, 4].includes(value.width) ? value.width : 2, dashed: value.dashed === true };
  } catch { return defaults; }
}

// Seed with a complete simple average; never invent a partial warm-up window.
export function exponentialAverage(points: PlotPoint[], length: number): PlotPoint[] {
  if (!Number.isInteger(length) || length < 1 || points.length < length) return [];
  const weight = 2 / (length + 1), result: PlotPoint[] = [];
  let value = points.slice(0, length).reduce((sum, p) => sum + p.value, 0) / length;
  result.push({ date: points[length - 1].date, value });
  for (const point of points.slice(length)) { value += weight * (point.value - value); result.push({ date: point.date, value }); }
  return result;
}
export function bollingerBands(points: PlotPoint[], length = 20, multiplier = 2) {
  const upper: PlotPoint[] = [], middle: PlotPoint[] = [], lower: PlotPoint[] = [];
  if (!Number.isInteger(length) || length < 2 || !Number.isFinite(multiplier) || multiplier < 0) return { upper, middle, lower };
  for (let i = length - 1; i < points.length; i++) {
    const window = points.slice(i - length + 1, i + 1), mean = window.reduce((sum, p) => sum + p.value, 0) / length;
    const deviation = Math.sqrt(window.reduce((sum, p) => sum + (p.value - mean) ** 2, 0) / length) * multiplier;
    middle.push({ date: points[i].date, value: mean }); upper.push({ date: points[i].date, value: mean + deviation }); lower.push({ date: points[i].date, value: mean - deviation });
  }
  return { upper, middle, lower };
}
export function relativeStrength(points: PlotPoint[], length = 14): PlotPoint[] {
  if (!Number.isInteger(length) || length < 1 || points.length <= length) return [];
  let gains = 0, losses = 0;
  const result: PlotPoint[] = [], rsi = () => losses === 0 ? (gains === 0 ? 50 : 100) : 100 - 100 / (1 + gains / losses);
  for (let i = 1; i <= length; i++) { const delta = points[i].value - points[i - 1].value; gains += Math.max(0, delta) / length; losses += Math.max(0, -delta) / length; }
  result.push({ date: points[length].date, value: rsi() });
  for (let i = length + 1; i < points.length; i++) {
    const delta = points[i].value - points[i - 1].value;
    gains = (gains * (length - 1) + Math.max(0, delta)) / length; losses = (losses * (length - 1) + Math.max(0, -delta)) / length;
    result.push({ date: points[i].date, value: rsi() });
  }
  return result;
}
export function macd(points: PlotPoint[], fast = 12, slow = 26, signalLength = 9) {
  const fastValues = new Map(exponentialAverage(points, fast).map(p => [p.date, p.value]));
  const line = exponentialAverage(points, slow).filter(p => fastValues.has(p.date)).map(p => ({ date: p.date, value: fastValues.get(p.date)! - p.value }));
  const signal = exponentialAverage(line, signalLength), signalValues = new Map(signal.map(p => [p.date, p.value]));
  return { line, signal, histogram: line.filter(p => signalValues.has(p.date)).map(p => ({ date: p.date, value: p.value - signalValues.get(p.date)! })) };
}
export const closePoints = (history: SemiconductorPrice[]): PlotPoint[] => history.map(p => ({ date: p.date, value: p.close }));
export function fibonacciLevels(start: Anchor, end: Anchor) {
  return [0, .236, .382, .5, .618, .786, 1].map(ratio => ({ ratio, value: end.value + (start.value - end.value) * ratio }));
}
