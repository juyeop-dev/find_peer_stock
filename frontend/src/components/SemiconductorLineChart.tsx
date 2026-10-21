import { useId, useLayoutEffect, useRef, useState } from "react";
import type { ChartPoint } from "../dataClient/semiconductorMath";

interface Props {
  points: ChartPoint[];
  title: string;
  unit: string;
}

const WIDTH = 760;
const HEIGHT = 280;
const LEFT = 100;
const TOP = 20;
const PLOT_WIDTH = 630;
const PLOT_HEIGHT = 210;

export function SemiconductorLineChart({ points, title, unit }: Props) {
  const [hovered, setHovered] = useState<number | null>(null);
  const chartRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const tooltipRef = useRef<HTMLDivElement>(null);
  const tooltipId = useId();
  const [tooltip, setTooltip] = useState({ left: 0, top: 0, visible: false });
  const values = points.map((point) => point.value);
  const minimum = Math.min(...values);
  const maximum = Math.max(...values);
  const padding = Math.max((maximum - minimum) * 0.12, Math.abs(maximum) * 0.01, 1e-12);
  const low = minimum - padding;
  const high = maximum + padding;
  const x = (index: number) => LEFT + index / (points.length - 1) * PLOT_WIDTH;
  const y = (value: number) => TOP + (high - value) / (high - low) * PLOT_HEIGHT;
  const path = points.map((point, index) => `${index === 0 ? "M" : "L"}${x(index).toFixed(1)},${y(point.value).toFixed(1)}`).join(" ");
  const rising = values.at(-1)! >= values[0];
  const active = Math.max(0, Math.min(hovered ?? points.length - 1, points.length - 1));
  useLayoutEffect(() => {
    const chart = chartRef.current, svg = svgRef.current, readout = tooltipRef.current;
    if (!chart || !svg || !readout || points.length < 2) return;
    function positionTooltip() {
      const matrix = svg!.getScreenCTM();
      if (!matrix) return;
      const point = new DOMPoint(x(active), y(points[active].value)).matrixTransform(matrix);
      const bounds = chart!.getBoundingClientRect();
      const minimum = chart!.scrollLeft + 6;
      const maximum = chart!.scrollLeft + chart!.clientWidth - readout!.offsetWidth - 6;
      setTooltip({
        left: Math.max(minimum, Math.min(maximum, point.x - bounds.left + chart!.scrollLeft - readout!.offsetWidth / 2)),
        top: point.y - bounds.top + chart!.scrollTop + 12,
        visible: point.x >= bounds.left && point.x <= bounds.left + chart!.clientWidth,
      });
    }
    positionTooltip();
    const observer = new ResizeObserver(positionTooltip);
    observer.observe(chart); observer.observe(svg); observer.observe(readout);
    chart.addEventListener("scroll", positionTooltip, { passive: true });
    return () => { observer.disconnect(); chart.removeEventListener("scroll", positionTooltip); };
  }, [active, points, low, high]);
  const formatted = (value: number) => unit === "원" ? `${Math.round(value).toLocaleString("ko-KR")}원`
    : unit === "조원" ? `${value.toFixed(2)}조원` : unit === "지수" ? value.toFixed(1)
    : `${new Intl.NumberFormat("ko-KR", { maximumFractionDigits: Math.abs(value) < 0.01 ? 8 : Math.abs(value) < 1 ? 4 : 2 }).format(value)} ${unit}`;

  if (points.length < 2) return <div className="semiChartEmpty">표시할 가격 기록이 충분하지 않습니다.</div>;
  return (
    <div ref={chartRef} className="semiChart" role="img" aria-label={`${title}: ${points[0].date}부터 ${points.at(-1)!.date}까지 ${unit} 추이`}>
      <svg ref={svgRef} viewBox={`0 0 ${WIDTH} ${HEIGHT}`} preserveAspectRatio="xMinYMid meet" tabIndex={0} aria-describedby={hovered !== null ? tooltipId : undefined}
        onPointerLeave={() => setHovered(null)} onFocus={() => setHovered(points.length - 1)} onBlur={() => setHovered(null)}
        onKeyDown={event => {
          if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
          event.preventDefault();
          setHovered(event.key === "Home" ? 0 : event.key === "End" ? points.length - 1 : Math.max(0, Math.min(points.length - 1, active + (event.key === "ArrowLeft" ? -1 : 1))));
        }}
        onPointerMove={(event) => {
          const matrix = event.currentTarget.getScreenCTM();
          if (!matrix) return;
          // Include the viewBox scale, preserved aspect ratio, and any scrolling.
          const position = new DOMPoint(event.clientX, event.clientY).matrixTransform(matrix.inverse()).x;
          setHovered(Math.max(0, Math.min(points.length - 1, Math.round((position - LEFT) / PLOT_WIDTH * (points.length - 1)))));
        }}>
        {[0, 0.5, 1].map((part) => {
          const value = high - (high - low) * part;
          const vertical = TOP + PLOT_HEIGHT * part;
          return <g key={part}>
            <line x1={LEFT} x2={LEFT + PLOT_WIDTH} y1={vertical} y2={vertical} className="semiGridLine" />
            <text x={LEFT - 9} y={vertical + 4} textAnchor="end" className="semiAxisText">{formatted(value)}</text>
          </g>;
        })}
        <path d={path} className={`semiLine ${rising ? "up" : "down"}`} />
        <line x1={x(active)} x2={x(active)} y1={TOP} y2={TOP + PLOT_HEIGHT} className="semiHoverLine" />
        <circle cx={x(active)} cy={y(points[active].value)} r="5" className={`semiDot ${rising ? "up" : "down"}`} />
        <text x={LEFT} y={HEIGHT - 14} className="semiAxisText">{points[0].date}</text>
        <text x={LEFT + PLOT_WIDTH} y={HEIGHT - 14} textAnchor="end" className="semiAxisText">{points.at(-1)!.date}</text>
      </svg>
      <div ref={tooltipRef} id={tooltipId} role="tooltip" className="semiChartReadout" style={{ left: tooltip.left, top: tooltip.top, visibility: tooltip.visible ? "visible" : "hidden" }}><strong>{points[active].date}</strong><span>{formatted(points[active].value)}</span></div>
    </div>
  );
}
