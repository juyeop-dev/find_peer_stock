import { useEffect, useRef } from "react";
import type { ReactNode } from "react";
import type { ComparisonSeries, PlotPoint } from "../dataClient/chartWorkspace";

export function ChartAnalysisDialog({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => { const node = dialog.current!; node.showModal(); return () => node.close(); }, []);
  return <dialog ref={dialog} className="chartAnalysisDialog" aria-label={title} onCancel={onClose} onKeyDown={event => { if (event.key === "Escape") event.stopPropagation(); }} onClick={event => { if (event.target === event.currentTarget) onClose(); }}>
    <div className="chartDialogHeading"><h3>{title}</h3><button type="button" aria-label={`${title} 닫기`} onClick={onClose}>×</button></div>{children}
  </dialog>;
}
export interface AnalysisPane { id: string; name: string; series: ComparisonSeries[]; histogram?: PlotPoint[]; bounds?: [number, number]; levels?: number[] }
export function ChartIndicatorPane({ pane, width, dates, range, active, onHover }: { pane: AnalysisPane; width: number; dates: string[]; range: [number, number]; active: number; onHover: (index: number) => void }) {
  const left = width < 480 ? 66 : 84, right = width - 22, top = 15, bottom = 135;
  const visible = (points: PlotPoint[]) => points.filter(p => p.date >= dates[range[0]] && p.date <= dates[range[1]]);
  const points = pane.series.flatMap(s => visible(s.points)), histogram = visible(pane.histogram ?? []);
  const values = [...points, ...histogram, ...((pane.levels ?? []).map(value => ({ value })))].map(p => p.value);
  const min = pane.bounds?.[0] ?? Math.min(0, ...values), max = pane.bounds?.[1] ?? Math.max(0, ...values);
  const padding = pane.bounds ? 0 : Math.max((max - min) * .1, .01), low = min - padding, high = max + padding;
  const indexes = new Map(dates.map((date, i) => [date, i]));
  const x = (date: string) => left + ((indexes.get(date) ?? 0) - range[0]) / Math.max(1, range[1] - range[0]) * (right - left);
  const y = (value: number) => top + (high - value) / Math.max(.01, high - low) * (bottom - top);
  return <section className="chartIndicatorPane" data-study={pane.id} aria-label={pane.name}>
    <div className="chartPaneLegend"><strong>{pane.name}</strong>{pane.series.map(s => <span key={s.ticker} style={{ color: s.color }}>{s.name} {s.points.find(p => p.date === dates[active])?.value.toFixed(2) ?? "—"}</span>)}</div>
    <svg viewBox={`0 0 ${width} 155`} role="img" aria-label={`${pane.name} 보조 지표 차트`} onPointerMove={event => { const bounds = event.currentTarget.getBoundingClientRect(), position = (event.clientX - bounds.left) / bounds.width * width; onHover(Math.max(range[0], Math.min(range[1], Math.round(range[0] + (position - left) / (right - left) * (range[1] - range[0]))))); }}>
      {(pane.levels ?? [0]).map(value => <g key={value}><line x1={left} x2={right} y1={y(value)} y2={y(value)} stroke="#b8c8d3" strokeDasharray="4 4" /><text x={left - 8} y={y(value) + 4} textAnchor="end" className="semiAxisText">{value}</text></g>)}
      {histogram.map(p => <rect key={p.date} x={x(p.date) - Math.max(1, (right - left) / Math.max(1, range[1] - range[0]) * .3)} y={Math.min(y(0), y(p.value))} width={Math.max(1, (right - left) / Math.max(1, range[1] - range[0]) * .6)} height={Math.max(.5, Math.abs(y(p.value) - y(0)))} fill={p.value >= 0 ? "#21a09588" : "#d56d7788"} />)}
      {pane.series.map(s => <path key={s.ticker} data-indicator={s.ticker} d={visible(s.points).map((p, i) => `${i ? "L" : "M"}${x(p.date)},${y(p.value)}`).join(" ")} fill="none" stroke={s.color} strokeWidth={1.5} />)}
      <line x1={x(dates[active])} x2={x(dates[active])} y1={top} y2={bottom} className="semiHoverLine" />
      {!points.length && <text x={(left + right) / 2} y={75} textAnchor="middle" className="semiAxisText">지표를 계산할 이전 거래일이 부족합니다.</text>}
    </svg>
  </section>;
}

export async function downloadAnalysisChart(root: HTMLElement) {
  const originals = [...root.querySelectorAll<SVGSVGElement>('.stockChartCanvas > svg, .chartIndicatorPane > svg')];
  if (!originals.length) return;
  const rendered = await Promise.all(originals.map(async original => {
    const clone = original.cloneNode(true) as SVGSVGElement, nodes = [original, ...original.querySelectorAll('*')], copies = [clone, ...clone.querySelectorAll('*')];
    nodes.forEach((node, i) => { const style = getComputedStyle(node); for (const key of ['fill', 'stroke', 'stroke-width', 'stroke-dasharray', 'opacity', 'font-size', 'font-family', 'font-weight']) (copies[i] as SVGElement).style.setProperty(key, style.getPropertyValue(key)); });
    clone.querySelectorAll('.chartDrawingHit,.chartChannelHit,.chartDrawingHandle,.chartChannelHandle').forEach(node => node.remove());
    clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg'); clone.setAttribute('width', String(original.viewBox.baseVal.width)); clone.setAttribute('height', String(original.viewBox.baseVal.height));
    const url = URL.createObjectURL(new Blob([new XMLSerializer().serializeToString(clone)], { type: 'image/svg+xml' }));
    try { const image = new Image(); image.src = url; await image.decode(); return image; } finally { URL.revokeObjectURL(url); }
  }));
  const canvas = document.createElement('canvas'); canvas.width = Math.max(...rendered.map(image => image.width)); canvas.height = rendered.reduce((sum, image) => sum + image.height, 0);
  const context = canvas.getContext('2d')!; context.fillStyle = '#ffffff'; context.fillRect(0, 0, canvas.width, canvas.height);
  let top = 0; for (const image of rendered) { context.drawImage(image, 0, top); top += image.height; }
  canvas.toBlob(blob => { if (!blob) return; const url = URL.createObjectURL(blob), link = document.createElement('a'); link.href = url; link.download = 'stock-peer-analysis.png'; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); });
}
