import type { SemiconductorPrice } from "./semiconductorTypes";

export type ChartScale = "price" | "percent";
export type DrawingTool = "move" | "trend" | "horizontal" | "vertical";
export interface Anchor { date: string; value: number }
export interface ChartDrawing {
  id: string; type: Exclude<DrawingTool, "move">; scale: ChartScale;
  start: Anchor; end: Anchor; color: string;
  channel?: { offset: number; visible: boolean; middle: boolean };
}
export interface PlotPoint { date: string; value: number }
export interface ComparisonInput { ticker: string; name: string; currency: string; history: SemiconductorPrice[]; color: string }
export interface ComparisonSeries { ticker: string; name: string; color: string; points: PlotPoint[] }
export const COMPARISON_COLORS = ["#8b5cf6", "#e59a18", "#1684cd"];
export const DRAWING_COLORS = ["#137d87", "#df7457", "#8b5cf6", "#2676bc"];
export const adjusted = (point: SemiconductorPrice) => Number.isFinite(point.adjusted_close) && point.adjusted_close > 0 ? point.adjusted_close : point.close;

// Only observed sessions shared by every selected listing enter a comparison.
// Different currencies remain local-currency returns, never a fabricated FX conversion.
export function compareHistories(base: ComparisonInput, others: ComparisonInput[], start: string, end: string): { start: string | null; series: ComparisonSeries[] } {
  const inputs = [base, ...others];
  const maps = inputs.map(input => new Map(input.history.filter(p => p.date >= start && p.date <= end).map(p => [p.date, adjusted(p)])));
  const dates = [...maps[0].keys()].filter(date => maps.every(map => map.has(date))).sort();
  if (dates.length < 2) return { start: null, series: [] };
  return { start: dates[0], series: inputs.map((input, index) => ({ ticker: input.ticker, name: input.name, color: input.color,
    points: dates.map(date => ({ date, value: (maps[index].get(date)! / maps[index].get(dates[0])! - 1) * 100 })) })) };
}

export function movingAverage(history: SemiconductorPrice[], length: number): PlotPoint[] {
  if (!Number.isInteger(length) || length < 1) return [];
  let sum = 0;
  const points: PlotPoint[] = [];
  for (let i = 0; i < history.length; i++) {
    sum += history[i].close;
    if (i >= length) sum -= history[i - length].close;
    if (i >= length - 1) points.push({ date: history[i].date, value: sum / length });
  }
  return points;
}

export function clampWindow(start: number, end: number, count: number): [number, number] {
  if (count < 2) return [0, Math.max(0, count - 1)];
  const size = Math.min(count - 1, Math.max(Math.min(9, count - 1), Math.round(end - start)));
  const left = Math.min(count - 1 - size, Math.max(0, Math.round(start)));
  return [left, left + size];
}
export function zoomWindow(window: [number, number], count: number, factor: number, anchor = .5): [number, number] {
  const width = window[1] - window[0], size = width * factor;
  const start = window[0] + (width - size) * Math.min(1, Math.max(0, anchor));
  return clampWindow(start, start + size, count);
}

// Coordinates are dates and prices/percentages, so drawings survive resizing and zoom.
export function parseDrawings(raw: string | null): ChartDrawing[] {
  try {
    const value: unknown = JSON.parse(raw ?? "[]");
    if (!Array.isArray(value)) return [];
    const anchor = (p: Anchor) => p && /^\d{4}-\d{2}-\d{2}$/.test(p.date) && Number.isFinite(p.value);
    return value.filter((d: ChartDrawing) => d && typeof d.id === "string" && ["trend", "horizontal", "vertical"].includes(d.type)
      && ["price", "percent"].includes(d.scale) && anchor(d.start) && anchor(d.end) && /^#[\da-f]{6}$/i.test(d.color)).slice(-100).map((d: ChartDrawing) => {
        const { channel, ...base } = d;
        return d.type === "trend" && channel && Number.isFinite(channel.offset) && typeof channel.visible === "boolean" && typeof channel.middle === "boolean"
          ? { ...base, channel: { offset: channel.offset, visible: channel.visible, middle: channel.middle } } : base;
      });
  } catch { return []; }
}
export const drawingStorageKey = (ticker: string, basis = "") => `stock-peer:drawings:v1:${ticker.toUpperCase()}:${basis}`;

export function channelSegments(drawing: ChartDrawing): { parallel: { start: Anchor; end: Anchor }; middle?: { start: Anchor; end: Anchor } } | null {
  if (drawing.type !== "trend" || !drawing.channel?.visible) return null;
  const shift = (offset: number) => ({ start: { ...drawing.start, value: drawing.start.value + offset }, end: { ...drawing.end, value: drawing.end.value + offset } });
  return { parallel: shift(drawing.channel.offset), ...(drawing.channel.middle ? { middle: shift(drawing.channel.offset / 2) } : {}) };
}

export function measureChange(from: number, to: number, scale: ChartScale): { delta: number; percent: number | null } {
  const denominator = scale === "percent" ? 100 + from : from;
  return { delta: to - from, percent: Number.isFinite(from) && Number.isFinite(to) && denominator > 0 ? (to - from) / denominator * 100 : null };
}

export function nearestDate(dates: string[], date: string): number {
  let left = 0, right = dates.length;
  while (left < right) { const middle = (left + right) >>> 1; if (dates[middle] < date) left = middle + 1; else right = middle; }
  if (left === 0) return 0;
  if (left === dates.length) return left - 1;
  return Date.parse(date) - Date.parse(dates[left - 1]) <= Date.parse(dates[left]) - Date.parse(date) ? left - 1 : left;
}
