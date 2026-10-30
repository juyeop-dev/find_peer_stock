import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from "react";
import { ImeSearchInput } from "./ImeSearchInput";
import { getStockHistory } from "../dataClient/stockHistoryClient";
import type { StockHistory } from "../dataClient/stockHistoryClient";
import { getChartSymbols, searchChartSymbols } from "../dataClient/chartComparisonClient";
import type { ChartSymbol } from "../dataClient/chartComparisonClient";
import { channelSegments, clampWindow, COMPARISON_COLORS, compareHistories, DRAWING_COLORS, drawingStorageKey, measureChange, movingAverage, nearestDate, parseDrawings, zoomWindow } from "../dataClient/chartWorkspace";
import type { Anchor, ChartDrawing, ChartScale, ComparisonSeries, DrawingTool } from "../dataClient/chartWorkspace";
import type { SemiconductorPrice } from "../dataClient/semiconductorTypes";
import "../styles/stockChartWorkspace.css";

interface Props { ticker: string; name: string; currency: string; history: SemiconductorPrice[]; points: SemiconductorPrice[]; period: string | number }
interface CompareRow { symbol: ChartSymbol; data?: StockHistory; loading: boolean; error?: string; color: string }
const TOOLS: [DrawingTool, string, string][] = [["move", "↔", "이동"], ["trend", "╱", "추세선"], ["horizontal", "―", "수평선"], ["vertical", "│", "수직선"]];
const MA_COLORS = ["#e8a12e", "#9862c6", "#318ca9"];

export function StockChartWorkspace({ ticker, name, currency, history, points, period }: Props) {
  const [symbols, setSymbols] = useState<ChartSymbol[]>([]), [query, setQuery] = useState("");
  const [searchOpen, setSearchOpen] = useState(false), [catalogError, setCatalogError] = useState("");
  const [comparisons, setComparisons] = useState<CompareRow[]>([]), [scale, setScale] = useState<ChartScale>("price");
  const [averages, setAverages] = useState<number[]>([]), [tool, setTool] = useState<DrawingTool>("move");
  const [color, setColor] = useState(DRAWING_COLORS[0]), [expanded, setExpanded] = useState(false);
  const controllers = useRef(new Map<string, AbortController>()), alive = useRef(true), catalogRequested = useRef(false);
  const root = useRef<HTMLDivElement>(null), searchId = useId();
  useEffect(() => { alive.current = true; return () => { alive.current = false; controllers.current.forEach(c => c.abort()); }; }, []);
  useEffect(() => {
    if (!expanded) return;
    const previouslyFocused = document.activeElement as HTMLElement | null;
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape") setExpanded(false);
      if (event.key === "Tab") {
        const controls = root.current?.querySelectorAll<HTMLElement>('button:not([disabled]),input:not([disabled]),svg[tabindex]');
        const first = controls?.[0], last = controls?.[controls.length - 1];
        if (event.shiftKey && (document.activeElement === first || document.activeElement === root.current)) { event.preventDefault(); last?.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
      }
    };
    document.addEventListener("keydown", close);
    const original = document.body.style.overflow; document.body.style.overflow = "hidden";
    root.current?.focus();
    return () => { document.body.style.overflow = original; document.removeEventListener("keydown", close); if (previouslyFocused?.isConnected) previouslyFocused.focus(); };
  }, [expanded]);
  async function loadCatalog() {
    setSearchOpen(true);
    if (catalogRequested.current) return;
    catalogRequested.current = true;
    try { const rows = await getChartSymbols(); if (alive.current) { setSymbols(rows); setCatalogError(""); } }
    catch (error) { if (alive.current) { catalogRequested.current = false; setCatalogError((error as Error).message); } }
  }
  async function addComparison(symbol: ChartSymbol) {
    const key = symbol.ticker.toUpperCase();
    if (key === ticker.toUpperCase() || comparisons.some(row => row.symbol.ticker === key) || controllers.current.has(key) || comparisons.length >= 3) return;
    const controller = new AbortController(); controllers.current.set(key, controller);
    const selectedColor = COMPARISON_COLORS.find(c => !comparisons.some(row => row.color === c)) ?? COMPARISON_COLORS[0];
    setComparisons(rows => [...rows, { symbol: { ...symbol, ticker: key }, loading: true, color: selectedColor }]);
    setQuery(""); setSearchOpen(false); setScale("percent");
    const update = (data: StockHistory) => {
      if (!controller.signal.aborted && alive.current) setComparisons(rows => rows.map(row => row.symbol.ticker === key ? { ...row, data } : row));
    };
    try {
      const data = await getStockHistory(key, symbol.exchange, controller.signal, false, undefined, update);
      if (!controller.signal.aborted && alive.current) setComparisons(rows => rows.map(row => row.symbol.ticker === key ? { ...row, data, loading: false } : row));
    } catch (error) {
      if (!controller.signal.aborted && alive.current) setComparisons(rows => rows.map(row => row.symbol.ticker === key ? { ...row, loading: false, error: (error as Error).message } : row));
    } finally { if (controllers.current.get(key) === controller) controllers.current.delete(key); }
  }
  function removeComparison(key: string) {
    controllers.current.get(key)?.abort(); controllers.current.delete(key);
    setComparisons(rows => rows.filter(row => row.symbol.ticker !== key));
  }
  const matches = useMemo(() => searchChartSymbols(symbols, query, [ticker, ...comparisons.map(row => row.symbol.ticker)]), [symbols, query, ticker, comparisons]);
  const directTicker = query.trim().toUpperCase();
  const directAllowed = /^[A-Z0-9][A-Z0-9.^:_-]{0,39}$/.test(directTicker) && directTicker !== ticker.toUpperCase() && !comparisons.some(row => row.symbol.ticker === directTicker);
  const loaded = useMemo(() => comparisons.filter(row => row.data).map(row => ({ ticker: row.symbol.ticker, name: row.symbol.name, currency: row.data!.currency, history: row.data!.history, color: row.color })), [comparisons]);
  const compared = useMemo(() => points.length ? compareHistories({ ticker, name, currency, history, color: "#137d87" }, loaded, points[0].date, points.at(-1)!.date) : { start: null, series: [] }, [ticker, name, currency, history, loaded, points]);
  const series: ComparisonSeries[] = scale === "percent" ? compared.series : [{ ticker, name, color: "#137d87", points: points.map(p => ({ date: p.date, value: p.close })) }];
  const indicators = useMemo(() => averages.map((length, i) => ({ ticker: `MA${length}`, name: `MA ${length}`, color: MA_COLORS[i], points: movingAverage(history, length).filter(p => points.length && p.date >= points[0].date && p.date <= points.at(-1)!.date) })), [averages, history, points]);
  const basis = scale === "price" ? `price:${currency}` : `percent:${compared.start}:${loaded.map(row => row.ticker).sort().join(",")}`;
  const chartUnit = scale === "percent" ? "%" : currency === "KRW" ? "원" : currency;
  return <div ref={root} tabIndex={-1} className={`stockChartWorkspace${expanded ? " isExpanded" : ""}`} role={expanded ? "dialog" : undefined} aria-modal={expanded ? true : undefined} aria-label={expanded ? `${name} 차트 크게 보기` : undefined}>
    <div className="chartWorkspaceToolbar">
      <div className="chartToolGroup" role="group" aria-label="차트 그리기 도구">{TOOLS.map(([value, icon, label]) => <button key={value} type="button" aria-pressed={tool === value} onClick={() => setTool(value)} title={label}><span aria-hidden="true">{icon}</span>{label}</button>)}</div>
      <div className="chartToolGroup" role="group" aria-label="차트 표시 단위">
        <button type="button" aria-pressed={scale === "price"} disabled={comparisons.length > 0} title={comparisons.length ? "종목 비교는 수익률 기준으로 표시합니다" : "제공된 종가"} onClick={() => setScale("price")}>가격</button>
        <button type="button" aria-pressed={scale === "percent"} onClick={() => setScale("percent")}>수익률 %</button>
      </div>
      <button type="button" className="chartExpandButton" aria-pressed={expanded} onClick={() => setExpanded(value => !value)}>{expanded ? "축소 보기" : "크게 보기"}</button>
    </div>
    <div className="chartCompareBar">
      <div className="chartSymbolSearch" onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget)) setSearchOpen(false); }}>
        <label htmlFor={searchId}>종목 비교 <small>최대 3개</small></label>
        <div className="chartSearchInput"><ImeSearchInput id={searchId} value={query} onValueChange={value => { setQuery(value); void loadCatalog(); }} disabled={comparisons.length >= 3} placeholder="종목명 또는 티커 검색" onFocus={() => void loadCatalog()} autoComplete="off" role="combobox" aria-autocomplete="list" aria-expanded={searchOpen && Boolean(query)} aria-controls={`${searchId}-results`}
          onKeyDown={event => {
            if (event.nativeEvent.isComposing) return;
            if (event.key === "Escape") setSearchOpen(false);
            if (event.key === "Enter") { event.preventDefault(); if (matches[0]) void addComparison(matches[0]); else if (directAllowed) void addComparison({ ticker: directTicker, name: directTicker }); }
            if (event.key === "ArrowDown") { event.preventDefault(); document.getElementById(`${searchId}-results`)?.querySelector<HTMLButtonElement>("button")?.focus(); }
          }} />
          <span aria-hidden="true">＋</span></div>
        {searchOpen && query.trim() && comparisons.length < 3 ? <div className="chartSearchResults" id={`${searchId}-results`} role="listbox" aria-label="비교할 종목 검색 결과">
          {matches.map(row => <button role="option" aria-selected={false} type="button" key={row.ticker} onClick={() => void addComparison(row)}><strong>{row.name}</strong><span>{row.ticker} · {row.exchange ?? row.market}</span></button>)}
          {directAllowed && !matches.some(row => row.ticker === directTicker) ? <button role="option" aria-selected={false} type="button" onClick={() => void addComparison({ ticker: directTicker, name: directTicker })}><strong>{directTicker} 직접 추가</strong><span>예: 005930.KS, AAPL, 2330.TW</span></button> : null}
          {!matches.length && !directAllowed ? <p>검색 결과가 없습니다.</p> : null}
        </div> : null}
      </div>
      <div className="chartIndicators" role="group" aria-label="이동평균선">{[20, 60, 120].map(length => <label key={length}><input type="checkbox" checked={averages.includes(length)} disabled={scale !== "price"} onChange={() => setAverages(values => values.includes(length) ? values.filter(v => v !== length) : [...values, length].sort((a, b) => a - b))} />MA {length}</label>)}</div>
    </div>
    {catalogError ? <p className="chartStatus" role="status">{catalogError}</p> : null}
    {comparisons.length > 0 ? <div className="chartComparisonChips">{comparisons.map(row => <div key={row.symbol.ticker} className={row.error ? "hasError" : ""} style={{ borderLeftColor: row.color }}><span><strong>{row.symbol.name}</strong> <small>{row.symbol.ticker}{row.loading ? " · 조회 중…" : ""}</small></span><button type="button" aria-label={`${row.symbol.ticker} 비교 제거`} onClick={() => removeComparison(row.symbol.ticker)}>×</button>{row.error || row.data?.warning ? <small role="status">{row.error ?? row.data?.warning}</small> : null}</div>)}</div> : null}
    {scale === "percent" ? <p className="chartBasis" role="status">{compared.start ? `${compared.start} = 0% · 모든 종목에 실제 기록이 있는 같은 거래일만 비교 · 각 통화 기준 수익률 (환율 미반영)` : "선택 기간에 공통 거래일이 2개 이상 있어야 비교할 수 있습니다. 기간을 늘리거나 비교 종목을 제거해 주세요."}</p> : null}
    <InteractiveStockPlot key={`${ticker}:${period}:${basis}`} series={series} indicators={scale === "price" ? indicators : []} anchorDates={scale === "price" ? history.map(p => p.date) : compared.series[0]?.points.map(p => p.date) ?? []} title={`${name} 주가`} unit={chartUnit} storageKey={drawingStorageKey(ticker, basis)} scale={scale} tool={tool} color={color} onToolChange={setTool} />
    <div className="chartWorkspaceFooter"><div className="chartDrawingColors" role="group" aria-label="그리기 색상">{DRAWING_COLORS.map((value, index) => <button type="button" key={value} style={{ background: value }} aria-label={["청록색", "주황색", "보라색", "파란색"][index]} aria-pressed={color === value} onClick={() => setColor(value)} />)}</div><span>휠로 확대 · 드래그로 이동 · 선을 선택해 끝점 수정 · Esc 취소</span></div>
  </div>;
}

interface PlotProps {
  series: ComparisonSeries[]; indicators: ComparisonSeries[]; anchorDates: string[]; title: string; unit: string;
  storageKey: string; scale: ChartScale; tool: DrawingTool; color: string; onToolChange: (value: DrawingTool) => void;
}
function InteractiveStockPlot({ series, indicators, anchorDates, title, unit, storageKey, scale, tool, color, onToolChange }: PlotProps) {
  const container = useRef<HTMLDivElement>(null), svg = useRef<SVGSVGElement>(null), tooltip = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(900), [window, setWindow] = useState<[number, number] | null>(null);
  const [hovered, setHovered] = useState<number | null>(null), [cursor, setCursor] = useState<Anchor | null>(null);
  const [draft, setDraft] = useState<Anchor | null>(null), [selected, setSelected] = useState<string | null>(null);
  const [referenceDate, setReferenceDate] = useState<string | null>(null), [pickingReference, setPickingReference] = useState(false);
  const [drawings, setDrawings] = useState<ChartDrawing[]>(() => { try { return parseDrawings(localStorage.getItem(storageKey)); } catch { return []; } });
  const [undo, setUndo] = useState<ChartDrawing[][]>([]), [storageError, setStorageError] = useState(false);
  const [tooltipPosition, setTooltipPosition] = useState({ left: 0, top: 0 });
  const drag = useRef<{ x: number; range: [number, number]; drawing?: ChartDrawing; endpoint?: "start" | "end"; channel?: "parallel" | "middle"; anchor: Anchor; original: ChartDrawing[]; moved: boolean } | null>(null);
  const tooltipId = useId(), clipId = useId().replaceAll(":", "");
  const dates = series[0]?.points.map(p => p.date) ?? [], count = dates.length;
  const range = clampWindow(window?.[0] ?? 0, window?.[1] ?? count - 1, count);
  const visibleDates = dates.slice(range[0], range[1] + 1), first = visibleDates[0], last = visibleDates.at(-1) ?? "";
  const left = width < 480 ? 66 : 84, right = width - 22, top = 22, bottom = width < 480 ? 272 : 302, height = bottom + 45;
  const plotWidth = right - left, plotHeight = bottom - top;
  const values = [...series, ...indicators].flatMap(row => row.points.filter(p => p.date >= first && p.date <= last).map(p => p.value));
  const minimum = values.length ? Math.min(...values) : 0, maximum = values.length ? Math.max(...values) : 1;
  const padding = Math.max((maximum - minimum) * .12, Math.abs(maximum) * .01, .01), low = minimum - padding, high = maximum + padding;
  const x = (date: string) => left + (nearestDate(dates, date) - range[0]) / Math.max(1, range[1] - range[0]) * plotWidth;
  const drawingX = (date: string) => left + (nearestDate(anchorDates, date) - nearestDate(anchorDates, first)) / Math.max(1, nearestDate(anchorDates, last) - nearestDate(anchorDates, first)) * plotWidth;
  const y = (value: number) => top + (high - value) / (high - low) * plotHeight;
  const formatted = (value: number) => scale === "percent" ? `${value >= 0 ? "+" : ""}${value.toFixed(2)}%` : new Intl.NumberFormat("ko-KR", { maximumFractionDigits: Math.abs(value) < .01 ? 6 : Math.abs(value) < 1 ? 4 : 2, notation: Math.abs(value) >= 1e8 ? "compact" : "standard" }).format(value) + (unit === "원" ? "원" : ` ${unit}`);
  const active = Math.max(range[0], Math.min(range[1], hovered ?? range[1]));
  const selectedTrend = drawings.find(d => d.id === selected && d.type === "trend");
  const defaultChannel = { offset: Number(((high - low) * .15).toPrecision(6)), visible: false, middle: false };
  const selectedChannel = selectedTrend?.channel ?? defaultChannel;
  const measurements = referenceDate ? series.map(row => {
    const from = row.points.find(p => p.date === referenceDate), to = row.points.find(p => p.date === dates[active]);
    return from && to ? { row, from, to, ...measureChange(from.value, to.value, scale) } : null;
  }).filter((value): value is NonNullable<typeof value> => value !== null) : [];
  function save(next: ChartDrawing[]) { setUndo(stack => [...stack.slice(-29), drawings]); setDrawings(next.slice(-100)); }
  function updateChannel(change: Partial<NonNullable<ChartDrawing["channel"]>>) {
    if (!selectedTrend) return;
    save(drawings.map(d => d.id === selectedTrend.id ? { ...d, channel: { ...selectedChannel, ...change } } : d));
  }
  function reset() { setWindow(null); setHovered(null); }
  function pointAt(event: { clientX: number; clientY: number }): Anchor {
    const matrix = svg.current?.getScreenCTM();
    const point = matrix ? new DOMPoint(event.clientX, event.clientY).matrixTransform(matrix.inverse()) : { x: left, y: top };
    const index = Math.max(range[0], Math.min(range[1], Math.round(range[0] + (point.x - left) / plotWidth * (range[1] - range[0]))));
    return { date: dates[index], value: high - Math.max(0, Math.min(plotHeight, point.y - top)) / plotHeight * (high - low) };
  }
  useEffect(() => {
    if (!container.current) return;
    const observer = new ResizeObserver(entries => setWidth(Math.max(260, entries[0].contentRect.width)));
    observer.observe(container.current); return () => observer.disconnect();
  }, []);
  useEffect(() => {
    try { localStorage.setItem(storageKey, JSON.stringify(drawings)); setStorageError(false); }
    catch { setStorageError(true); }
  }, [drawings, storageKey]);
  useEffect(() => { setDraft(null); drag.current = null; if (tool !== "move") setPickingReference(false); }, [tool]);
  useEffect(() => {
    const node = svg.current; if (!node) return;
    const wheel = (event: WheelEvent) => {
      if (event.ctrlKey || event.metaKey) return;
      event.preventDefault();
      const bounds = node.getBoundingClientRect(), anchor = (event.clientX - bounds.left - left) / plotWidth;
      setWindow(current => zoomWindow(current ?? [0, count - 1], count, event.deltaY > 0 ? 1.2 : .8, anchor));
    };
    node.addEventListener("wheel", wheel, { passive: false }); return () => node.removeEventListener("wheel", wheel);
  }, [count, left, plotWidth]);
  useLayoutEffect(() => {
    if (!container.current || !tooltip.current || !svg.current || !count) return;
    const target = series[0]?.points[active];
    if (!target) return;
    const matrix = svg.current.getScreenCTM(); if (!matrix) return;
    const position = new DOMPoint(x(target.date), y(target.value)).matrixTransform(matrix), bounds = container.current.getBoundingClientRect();
    setTooltipPosition({ left: Math.max(6, Math.min(container.current.clientWidth - tooltip.current.offsetWidth - 6, position.x - bounds.left - tooltip.current.offsetWidth / 2)), top: Math.max(0, Math.min(container.current.clientHeight - tooltip.current.offsetHeight - 6, position.y - bounds.top + 12)) });
  }, [active, count, width, first, last, series, bottom, referenceDate]);
  function cancel() { setDraft(null); setSelected(null); setPickingReference(false); if (drag.current?.drawing) setDrawings(drag.current.original); drag.current = null; onToolChange("move"); }
  const visibleDrawings = drawings.filter(d => d.scale === scale);
  const preview: ChartDrawing | null = draft && cursor ? { id: "draft", type: "trend", scale, start: draft, end: cursor, color } : null;
  function drawLine(drawing: ChartDrawing) {
    const { start, end, type } = drawing;
    if (type === "vertical" && (start.date < first || start.date > last)) return null;
    if (type === "trend" && ([start.date, end.date].every(date => date < first) || [start.date, end.date].every(date => date > last))) return null;
    const coordinates = type === "horizontal" ? { x1: left, x2: right, y1: y(start.value), y2: y(start.value) }
      : type === "vertical" ? { x1: drawingX(start.date), x2: drawingX(start.date), y1: top, y2: bottom }
      : { x1: drawingX(start.date), x2: drawingX(end.date), y1: y(start.value), y2: y(end.value) };
    const channel = channelSegments(drawing);
    const parallel = channel ? { x1: drawingX(channel.parallel.start.date), x2: drawingX(channel.parallel.end.date), y1: y(channel.parallel.start.value), y2: y(channel.parallel.end.value) } : null;
    return <g key={drawing.id} className={`chartDrawing${selected === drawing.id ? " selected" : ""}`} data-drawing={drawing.id}>
      <line {...coordinates} stroke={drawing.color} strokeWidth={selected === drawing.id ? 3 : 2} vectorEffect="non-scaling-stroke" pointerEvents="none" strokeDasharray={drawing.id === "draft" ? "5 4" : undefined} />
      {drawing.id !== "draft" ? <line {...coordinates} stroke="transparent" strokeWidth={18} data-drawing={drawing.id} className="chartDrawingHit" /> : null}
      {channel && parallel ? <>
        <polygon points={`${coordinates.x1},${coordinates.y1} ${coordinates.x2},${coordinates.y2} ${parallel.x2},${parallel.y2} ${parallel.x1},${parallel.y1}`} fill={drawing.color} opacity={.06} pointerEvents="none" />
        <line {...parallel} stroke={drawing.color} strokeWidth={2} vectorEffect="non-scaling-stroke" pointerEvents="none" className="chartParallelLine" />
        <line {...parallel} stroke="transparent" strokeWidth={16} data-drawing={drawing.id} data-channel="parallel" className="chartChannelHit" />
        {channel.middle ? <><line x1={drawingX(channel.middle.start.date)} x2={drawingX(channel.middle.end.date)} y1={y(channel.middle.start.value)} y2={y(channel.middle.end.value)} stroke={drawing.color} strokeWidth={1.5} strokeDasharray="6 4" vectorEffect="non-scaling-stroke" pointerEvents="none" className="chartMiddleLine" /><line x1={parallel.x1} x2={parallel.x2} y1={(coordinates.y1 + parallel.y1) / 2} y2={(coordinates.y2 + parallel.y2) / 2} stroke="transparent" strokeWidth={12} data-drawing={drawing.id} data-channel="middle" className="chartChannelHit" /></> : null}
        {selected === drawing.id ? <circle cx={(parallel.x1 + parallel.x2) / 2} cy={(parallel.y1 + parallel.y2) / 2} r={6} fill="white" stroke={drawing.color} strokeWidth={2} data-drawing={drawing.id} data-channel="parallel" className="chartChannelHandle" /> : null}
      </> : null}
      {selected === drawing.id ? (type === "trend" ? ["start", "end"] as const : ["start"] as const).map(endpoint => <circle key={endpoint} cx={type === "horizontal" ? left + plotWidth / 2 : drawingX(drawing[endpoint].date)} cy={type === "vertical" ? top + plotHeight / 2 : y(drawing[endpoint].value)} r={6} fill="white" stroke={drawing.color} strokeWidth={2} data-drawing={drawing.id} data-endpoint={endpoint} className="chartDrawingHandle" />) : null}
    </g>;
  }
  return <>
    <div className="chartNavigation" role="group" aria-label="차트 확대와 그리기 관리">
      <button type="button" aria-label="차트 확대" disabled={count < 2} onClick={() => setWindow(zoomWindow(range, count, .65))}>＋ 확대</button>
      <button type="button" aria-label="차트 축소" disabled={count < 2} onClick={() => setWindow(zoomWindow(range, count, 1.5))}>− 축소</button>
      <button type="button" onClick={reset}>범위 초기화</button>
      <span className="chartToolbarDivider" />
      <button type="button" disabled={!undo.length} onClick={() => { setDrawings(undo.at(-1)!); setUndo(stack => stack.slice(0, -1)); setSelected(null); }}>실행 취소</button>
      <button type="button" disabled={!selected} onClick={() => { save(drawings.filter(d => d.id !== selected)); setSelected(null); }}>선택 삭제</button>
      <button type="button" disabled={!drawings.length} onClick={() => { save([]); setSelected(null); }}>선 모두 지우기</button>
    </div>
    <div className="chartChannelSettings" role="group" aria-label="추세선 평행선과 중간선 설정">
      <label className="chartTrendSelect">추세선 선택<select aria-label="채널을 설정할 추세선" value={selectedTrend?.id ?? ""} onChange={event => { setSelected(event.target.value || null); onToolChange("move"); }}><option value="">추세선을 그리거나 선택하세요</option>{drawings.filter(d => d.type === "trend").map((d, i) => <option key={d.id} value={d.id}>추세선 {i + 1} · {d.start.date} ~ {d.end.date}</option>)}</select></label>
      <label><input type="checkbox" aria-label="평행선 표시" disabled={!selectedTrend} checked={Boolean(selectedTrend && selectedChannel.visible)} onChange={event => updateChannel({ visible: event.target.checked, ...(!event.target.checked ? { middle: false } : {}) })} />평행선 표시</label>
      <label><input type="checkbox" aria-label="중간선 표시" disabled={!selectedTrend || !selectedChannel.visible} checked={Boolean(selectedTrend && selectedChannel.visible && selectedChannel.middle)} onChange={event => updateChannel({ middle: event.target.checked })} />중간선 표시</label>
      {selectedTrend && selectedChannel.visible ? <><label className="chartChannelOffset">선 간격 ({scale === "percent" ? "%p" : unit})<input key={`${selectedTrend.id}:${selectedChannel.offset}`} type="number" step="any" aria-label="평행선 간격" defaultValue={Number(selectedChannel.offset.toPrecision(8))} onBlur={event => { const value = Number(event.currentTarget.value); if (event.currentTarget.value.trim() && Number.isFinite(value) && value !== selectedChannel.offset) updateChannel({ offset: value }); }} onKeyDown={event => { if (event.key === "Enter") event.currentTarget.blur(); }} /></label><button type="button" onClick={() => updateChannel({ offset: -selectedChannel.offset })}>위·아래 반전</button></> : null}
    </div>
    <p className="chartToolHint" role="status">{pickingReference ? "기준으로 삼을 날짜를 클릭하세요. 해당 날짜의 실제 종가로 고정합니다." : draft ? "끝점을 한 번 더 선택하세요. Esc로 취소합니다." : tool === "trend" ? "시작점과 끝점을 차례로 선택해 추세선을 그리세요." : tool === "horizontal" ? "차트에서 가격 위치를 선택해 수평선을 그리세요." : tool === "vertical" ? "차트에서 날짜를 선택해 수직선을 그리세요." : "빈 곳 클릭으로 종가 기준점을 고정하고, 다른 날짜에 마우스를 올려 등락률을 비교하세요. 드래그하면 차트가 이동합니다."}{selectedTrend?.channel?.visible ? " 평행선 중앙 손잡이를 위·아래로 끌면 선 간격이 바뀝니다." : ""}{storageError ? " 브라우저 저장 공간을 사용할 수 없어 현재 화면에서만 유지됩니다." : " 선은 이 브라우저에 종목별로 자동 저장됩니다."}</p>
    <div ref={container} className="semiChart stockChartCanvas" role="img" aria-label={count >= 2 ? `${title}: ${first}부터 ${last}까지 ${unit} 추이` : `${title}: 비교 가능한 일봉 부족`}>
      {count < 2 ? <div className="semiChartEmpty">표시할 가격 기록이 충분하지 않습니다.</div> : <>
        <div className="chartSeriesLegend">{[...series, ...indicators].map(row => {
          const point = row.points.find(p => p.date === dates[active]);
          return <span key={row.ticker}><i style={{ background: row.color }} /><strong>{row.name}</strong><small>{point ? formatted(point.value) : "해당일 기록 없음"}</small></span>;
        })}</div>
        <svg ref={svg} viewBox={`0 0 ${width} ${height}`} tabIndex={0} data-tool={pickingReference ? "reference" : tool} aria-label="주가 차트. 방향키로 날짜 이동, Enter로 기준점 고정, 더하기와 빼기로 확대·축소, Home과 End로 처음과 끝 조회" aria-describedby={tooltipId} style={{ cursor: tool === "move" && !pickingReference ? "grab" : "crosshair", height }}
          onDoubleClick={reset} onPointerLeave={event => { if (!drag.current && event.pointerType !== "touch") { setHovered(null); setCursor(null); } }}
          onFocus={() => setHovered(range[1])} onBlur={() => { if (!drag.current) setHovered(null); }}
          onKeyDown={event => {
            if (event.key === "Escape") { event.preventDefault(); cancel(); }
            else if ((event.key === "Enter" || event.key === " ") && tool === "move") { event.preventDefault(); setReferenceDate(dates[active]); setPickingReference(false); }
            else if (event.key === "Delete" || event.key === "Backspace") { if (selected) { event.preventDefault(); save(drawings.filter(d => d.id !== selected)); setSelected(null); } }
            else if ((event.ctrlKey || event.metaKey) && event.key === "z") { event.preventDefault(); if (undo.length) { setDrawings(undo.at(-1)!); setUndo(stack => stack.slice(0, -1)); } }
            else if (["+", "=", "-"].includes(event.key)) { event.preventDefault(); setWindow(zoomWindow(range, count, event.key === "-" ? 1.4 : .7)); }
            else if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) { event.preventDefault(); setHovered(event.key === "Home" ? range[0] : event.key === "End" ? range[1] : Math.max(range[0], Math.min(range[1], active + (event.key === "ArrowLeft" ? -1 : 1)))); }
          }}
          onPointerDown={event => {
            if (event.button !== 0) return;
            const position = pointAt(event), target = event.target as SVGElement;
            const drawing = tool === "move" && !pickingReference ? drawings.find(d => d.id === target.dataset.drawing) : undefined;
            event.currentTarget.focus();
            if (tool !== "move") {
              if (tool === "trend" && !draft) { setDraft(position); setCursor(position); return; }
              const start = draft ?? position;
              if (tool === "trend" && start.date === position.date) return;
              const id = crypto.randomUUID();
              save([...drawings, { id, type: tool, scale, start, end: position, color }]); setDraft(null);
              if (tool === "trend") { setSelected(id); onToolChange("move"); }
              return;
            }
            setSelected(drawing?.id ?? null);
            drag.current = { x: event.clientX, range, anchor: position, drawing, endpoint: target.dataset.endpoint as "start" | "end" | undefined, channel: target.dataset.channel as "parallel" | "middle" | undefined, original: drawings, moved: false };
            event.currentTarget.setPointerCapture(event.pointerId);
          }}
          onPointerMove={event => {
            const position = pointAt(event); setCursor(position); setHovered(nearestDate(dates, position.date));
            const current = drag.current; if (!current) return;
            current.moved ||= Math.abs(event.clientX - current.x) > 2 || Math.abs(position.value - current.anchor.value) > (high - low) * .005;
            if (current.drawing) {
              const original = current.drawing, offset = nearestDate(dates, position.date) - nearestDate(dates, current.anchor.date), value = position.value - current.anchor.value;
              if (current.channel && original.channel) {
                const channel = { ...original.channel, offset: original.channel.offset + value * (current.channel === "middle" ? 2 : 1) };
                setDrawings(current.original.map(d => d.id === original.id ? { ...original, channel } : d)); return;
              }
              const move = (p: Anchor): Anchor => ({ date: dates[Math.max(0, Math.min(count - 1, nearestDate(dates, p.date) + offset))], value: p.value + value });
              const updated = current.endpoint ? { ...original, [current.endpoint]: position } : { ...original, start: move(original.start), end: move(original.end) };
              if (original.type === "horizontal") updated.end = { ...updated.end, value: updated.start.value };
              setDrawings(current.original.map(d => d.id === original.id ? updated : d));
            } else {
              const shift = (current.x - event.clientX) / plotWidth * (current.range[1] - current.range[0]);
              setWindow(clampWindow(current.range[0] + shift, current.range[1] + shift, count));
            }
          }}
          onPointerUp={event => { const current = drag.current; if (current?.drawing && current.moved) setUndo(stack => [...stack.slice(-29), current.original]); if (current && !current.drawing && !current.moved) { if (!referenceDate || pickingReference) setReferenceDate(current.anchor.date); setPickingReference(false); setHovered(nearestDate(dates, current.anchor.date)); } drag.current = null; if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId); }}
          onPointerCancel={() => { if (drag.current?.drawing) setDrawings(drag.current.original); drag.current = null; setDraft(null); }}>
          <defs><clipPath id={clipId}><rect x={left} y={top} width={plotWidth} height={plotHeight} /></clipPath></defs>
          {[0, .25, .5, .75, 1].map(part => <g key={part}><line x1={left} x2={right} y1={top + part * plotHeight} y2={top + part * plotHeight} className="semiGridLine" /><text x={left - 8} y={top + part * plotHeight + 4} textAnchor="end" className="semiAxisText">{formatted(high - part * (high - low))}</text></g>)}
          <g clipPath={`url(#${clipId})`}>
            {referenceDate && referenceDate >= first && referenceDate <= last ? <>
              <rect x={Math.min(x(referenceDate), x(dates[active]))} y={top} width={Math.abs(x(dates[active]) - x(referenceDate))} height={plotHeight} className="chartMeasurementShade" pointerEvents="none" />
              <line x1={x(referenceDate)} x2={x(referenceDate)} y1={top} y2={bottom} className="chartReferenceLine" pointerEvents="none" />
              {series[0]?.points.find(p => p.date === referenceDate) ? <circle cx={x(referenceDate)} cy={y(series[0].points.find(p => p.date === referenceDate)!.value)} r={5} className="chartReferenceDot" pointerEvents="none" /> : null}
            </> : null}
            {scale === "percent" ? <line x1={left} x2={right} y1={y(0)} y2={y(0)} className="chartZeroLine" /> : null}
            {[...series, ...indicators].map((row, i) => <path key={row.ticker} data-series={row.ticker} d={row.points.filter(p => p.date >= first && p.date <= last).map((p, index) => `${index ? "L" : "M"}${x(p.date).toFixed(2)},${y(p.value).toFixed(2)}`).join(" ")} className={i < series.length ? "semiLine chartPriceLine" : "chartAverageLine"} style={{ stroke: row.color }} />)}
            <line x1={x(dates[active])} x2={x(dates[active])} y1={top} y2={bottom} className="semiHoverLine" />
            {cursor && hovered !== null ? <line x1={left} x2={right} y1={y(cursor.value)} y2={y(cursor.value)} className="semiHoverLine" /> : null}
            {series.map(row => { const point = row.points.find(p => p.date === dates[active]); return point ? <circle key={row.ticker} className="semiDot" cx={x(point.date)} cy={y(point.value)} r={4} style={{ fill: row.color }} /> : null; })}
            {visibleDrawings.map(drawLine)}{preview ? drawLine(preview) : null}
          </g>
          <text x={left} y={bottom + 24} className="semiAxisText">{first}</text><text x={right} y={bottom + 24} textAnchor="end" className="semiAxisText">{last}</text>
        </svg>
        <div ref={tooltip} id={tooltipId} className="semiChartReadout chartWorkspaceReadout" role="tooltip" style={{ left: tooltipPosition.left, top: tooltipPosition.top, visibility: hovered !== null ? "visible" : "hidden" }}><strong>{dates[active]}</strong>{series.map(row => { const point = row.points.find(p => p.date === dates[active]), measured = measurements.find(m => m.row.ticker === row.ticker); return <span key={row.ticker} style={{ color: row.color }}>{row.name}: {point ? formatted(point.value) : "미제공"}{measured?.percent !== null && measured?.percent !== undefined ? ` · 기준 대비 ${measured.percent >= 0 ? "+" : ""}${measured.percent.toFixed(2)}%` : ""}</span>; })}</div>
      </>}
    </div>
    <div className="chartMeasurementPanel" role="group" aria-label="클릭 기준점 대비 등락률">
      <div className="chartMeasurementHeading"><strong>기준점 대비 등락률</strong><button type="button" aria-pressed={pickingReference} disabled={count < 2} onClick={() => { setReferenceDate(null); setPickingReference(true); onToolChange("move"); svg.current?.focus(); }}>{referenceDate ? "기준점 다시 선택" : "기준점 선택"}</button>{referenceDate ? <button type="button" onClick={() => { setReferenceDate(null); setPickingReference(false); }}>기준점 해제</button> : null}</div>
      {referenceDate ? <><p className="chartMeasurementDates">기준 {referenceDate} → 조회 {dates[active]}{scale === "percent" ? " · 조정 종가 수익률 기준" : " · 실제 종가 기준"}</p><div className="chartMeasurementValues">{measurements.map(m => <div key={m.row.ticker} data-measure-series={m.row.ticker} data-from={m.from.value} data-to={m.to.value} data-percent={m.percent ?? ""}><span><i style={{ background: m.row.color }} />{m.row.name}</span><strong className={(m.percent ?? 0) >= 0 ? "semiUp" : "semiDown"}>{m.percent === null ? "계산 불가" : `${m.percent >= 0 ? "+" : ""}${m.percent.toFixed(2)}%`}</strong><small>{formatted(m.from.value)} → {formatted(m.to.value)} · {scale === "percent" ? `${m.delta >= 0 ? "+" : ""}${m.delta.toFixed(2)}%p` : `${m.delta >= 0 ? "+" : ""}${formatted(m.delta)}`}</small></div>)}</div></> : <p>차트를 한 번 클릭해 기준 날짜를 고정한 뒤, 다른 날짜에 마우스를 올리거나 터치해 등락률을 확인하세요.</p>}
    </div>
    {count >= 2 ? <div className="chartRangeControls"><label>시작일<input aria-label="차트 시작일" type="date" min={dates[0]} max={dates.at(-1)} value={first} onChange={event => { if (event.target.value) setWindow(clampWindow(nearestDate(dates, event.target.value), range[1], count)); }} /></label><label>끝일<input aria-label="차트 끝일" type="date" min={dates[0]} max={dates.at(-1)} value={last} onChange={event => { if (event.target.value) { const end = nearestDate(dates, event.target.value); setWindow(clampWindow(Math.min(range[0], end - Math.min(9, count - 1)), end, count)); } }} /></label><span>{visibleDates.length}개 거래일</span></div> : null}
  </>;
}
