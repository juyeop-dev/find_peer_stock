import { useEffect, useId, useMemo, useRef, useState } from "react";
import { getChartSymbols, searchChartSymbols, similarChartSymbols } from "../dataClient/chartComparisonClient";
import type { ChartSymbol } from "../dataClient/chartComparisonClient";
import { getReplayMarket } from "../dataClient/chartReplayClient";
import { hasOHLC, initialReplaySettings, restoreReplaySettings, REPLAY_PRESET, replayRange, replayReturns, validReplayDate } from "../dataClient/chartReplay";
import type { ReplayInterval, ReplayMarket, ReplaySelection, ReplaySettings as Settings } from "../dataClient/chartReplay";
import { ImeSearchInput } from "./ImeSearchInput";
import { ReplayCharts } from "./ReplayCharts";
import { classifiedSectorStock } from "../dataClient/sectorRankings";
import "../styles/chartReplay.css";

const BUILTINS: ChartSymbol[] = REPLAY_PRESET.map(row => ({ ticker: row.ticker, name: row.name }));
function useMarket(selection: ReplaySelection, retry: number) {
  const [result, setResult] = useState<{ market?: ReplayMarket; error?: string; loading: boolean }>({ loading: true });
  useEffect(() => {
    const controller = new AbortController(); setResult({ loading: true });
    if (!selection.ticker) { setResult({ loading: false }); return () => controller.abort(); }
    void getReplayMarket(selection.ticker, selection.name, selection.exchange, controller.signal).then(market => {
      if (!controller.signal.aborted) setResult({ market, loading: false });
    }).catch(error => { if (!controller.signal.aborted) setResult({ error: (error as Error).message, loading: false }); });
    return () => controller.abort();
  }, [selection.ticker, selection.name, selection.exchange, retry]);
  // Do not flash a previously selected symbol while the next effect loads.
  return result.market && result.market.ticker !== selection.ticker ? { loading: true } : result;
}

export function ChartReplayWorkspace({ ticker, name, exchange, active = true }: { ticker?: string; name?: string; exchange?: string; active?: boolean }) {
  const storageKey = `stock-peer:replay:v1:${ticker ?? "markets"}`;
  const [settings, setSettings] = useState(() => {
    const fallback = initialReplaySettings(ticker, name, exchange);
    try { return restoreReplaySettings(localStorage.getItem(storageKey), fallback, Boolean(ticker)); }
    catch { return fallback; }
  });
  const [playing, setPlaying] = useState(false), [expanded, setExpanded] = useState(false), [fit, setFit] = useState(0);
  const [retry, setRetry] = useState([0, 0]), [notice, setNotice] = useState("");
  const [peerStatus, setPeerStatus] = useState("");
  const root = useRef<HTMLElement>(null);
  const comparisonBase = settings.selections[0], comparisonTicker = settings.selections[1].ticker;
  const peerPending = Boolean(ticker && settings.autoPeer && !comparisonTicker && (!peerStatus || peerStatus.startsWith("사업")));
  useEffect(() => {
    if (!ticker || !active || !settings.autoPeer || comparisonTicker) return;
    const controller = new AbortController();
    setPeerStatus("사업·업종이 비슷한 종목의 가격 이력을 확인하고 있습니다…");
    void (async () => {
      const rows = (await getChartSymbols()).map(row => classifiedSectorStock({ ...row, sector: row.sector ?? "Unclassified", industry: row.industry ?? "Unclassified" }));
      for (const { symbol, reason } of similarChartSymbols(rows, comparisonBase.ticker)) {
        if (controller.signal.aborted) return;
        try {
          const market = await getReplayMarket(symbol.ticker, symbol.name, symbol.exchange, controller.signal);
          if (replayRange(market.bars, comparisonBase.start, comparisonBase.end).length < 2) continue;
          if (controller.signal.aborted) return;
          setPeerStatus("");
          setSettings(previous => previous.selections[1].ticker ? previous : { ...previous,
            selections: [previous.selections[0], { ticker: symbol.ticker, name: symbol.name, exchange: symbol.exchange,
              start: previous.selections[0].start, end: previous.selections[0].end }], peerReason: reason });
          return;
        } catch { if (controller.signal.aborted) return; }
      }
      if (!controller.signal.aborted) setPeerStatus("비교 기간의 이력이 있는 유사 종목을 찾지 못했습니다. B에서 비교할 종목을 직접 선택해 주세요.");
    })().catch(() => { if (!controller.signal.aborted) setPeerStatus("유사 종목 목록을 불러오지 못했습니다. B에서 티커를 직접 입력해 비교할 수 있습니다."); });
    return () => controller.abort();
  }, [ticker, active, settings.autoPeer, comparisonBase, comparisonTicker]);
  const first = useMarket(settings.selections[0], retry[0]), second = useMarket(settings.selections[1], retry[1]);
  const markets = useMemo(() => [first.market, second.market], [first.market, second.market]);
  const ranges = useMemo(() => settings.selections.map((selection, i) => replayRange(markets[i]?.bars ?? [], selection.start, selection.end)), [markets, settings.selections]);
  const errors = [first, second].map((row, i) => !settings.selections[i].ticker ? "비교할 종목을 선택해 주세요." : row.error ?? (!row.loading && ranges[i].length < 2 ? "선택 기간에 거래일이 2개 이상 필요합니다. 제공 범위를 확인해 주세요." : ""));
  const ready = !first.loading && !second.loading && errors.every(error => !error);
  // Stop at the shorter history: both panels advance one actual daily session
  // per tick. Different market holidays do not create artificial bars.
  const maximum = ready ? Math.min(...ranges.map(rows => rows.length)) : 1;
  // A newly applied selection opens its whole available comparison period.
  // Keep that intent while either market is still loading.
  const count = Math.min(settings.count ?? maximum, maximum);
  const candleAvailable = ranges.every(rows => rows.length > 0 && rows.every(hasOHLC));
  const patch = (value: Partial<Settings>) => { setSettings(previous => ({ ...previous, ...value })); setNotice(""); };
  useEffect(() => { if (!active) { setPlaying(false); setExpanded(false); } }, [active]);
  useEffect(() => {
    if (!playing || !ready || count >= maximum) { if (playing) setPlaying(false); return; }
    const timer = window.setInterval(() => setSettings(previous => ({ ...previous, count: Math.min((previous.count ?? maximum) + 1, maximum) })), 1000 / settings.speed);
    return () => window.clearInterval(timer);
  }, [playing, ready, maximum, count, settings.speed]);
  useEffect(() => {
    if (!expanded) return;
    const previous = document.activeElement as HTMLElement | null, overflow = document.body.style.overflow;
    const keydown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setExpanded(false);
      if (event.key === "Tab") {
        const nodes = root.current?.querySelectorAll<HTMLElement>('button:not([disabled]),input:not([disabled]),select:not([disabled]),a[href]');
        const start = nodes?.[0], end = nodes?.[nodes.length - 1];
        if (event.shiftKey && (document.activeElement === start || document.activeElement === root.current)) { event.preventDefault(); end?.focus(); }
        else if (!event.shiftKey && document.activeElement === end) { event.preventDefault(); start?.focus(); }
      }
    };
    document.body.style.overflow = "hidden"; document.addEventListener("keydown", keydown); root.current?.focus();
    return () => { document.body.style.overflow = overflow; document.removeEventListener("keydown", keydown); if (previous?.isConnected) previous.focus(); };
  }, [expanded]);

  function select(index: number, selection: ReplaySelection) {
    setPlaying(false);
    const selections = settings.selections.map((row, i) => i === index ? selection : row);
    if (index === 0 && settings.autoPeer) selections[1] = { ticker: "", name: "비교 종목 선택", start: selection.start, end: selection.end };
    patch({ selections, count: null, autoPeer: index === 1 ? false : settings.autoPeer, peerReason: undefined });
    setPeerStatus("");
    setFit(value => value + 1);
  }
  function save() {
    try { localStorage.setItem(storageKey, JSON.stringify({ ...settings, count, version: 2 })); setNotice("종목·기간·차트 설정과 재생 위치를 이 브라우저에 저장했습니다."); }
    catch { setNotice("브라우저 저장 공간에 접근할 수 없습니다. 현재 화면은 계속 사용할 수 있습니다."); }
  }
  return <section ref={root} tabIndex={-1} className={`semiPanel chartReplayWorkspace${expanded ? " replayExpanded" : ""}`} role={expanded ? "dialog" : undefined} aria-modal={expanded ? true : undefined} aria-label="차트 리플레이 작업 공간">
    <div className="replayHeading"><div><p className="eyebrow">CHART WORKSPACE</p><h2>차트 비교 · 리플레이</h2><p>{ticker ? "비슷한 종목의 같은 기간 수익률을 겹쳐 비교하세요." : "다른 시기의 시장을 같은 속도로 살펴보세요."}</p></div><div className="replayHeadingActions"><button type="button" disabled={!ready} onClick={save}>설정 저장</button><button type="button" aria-pressed={expanded} onClick={() => setExpanded(value => !value)}>{expanded ? "크게 보기 닫기" : "크게 보기"}</button></div></div>
    <div className="replayToolbar">
      <div className="replaySegment" role="group" aria-label="비교 레이아웃"><button type="button" aria-pressed={!settings.overlay} onClick={() => patch({ overlay: false })}>나란히 보기</button><button type="button" aria-pressed={settings.overlay} onClick={() => patch({ overlay: true })}>수익률 겹쳐 보기</button></div>
      <label>봉 간격<select aria-label="리플레이 봉 간격" value={settings.interval} disabled={settings.overlay} onChange={event => patch({ interval: event.target.value as ReplayInterval })}><option value="day">일</option><option value="week">주</option><option value="month">월</option></select></label>
      <label>차트 종류<select aria-label="리플레이 차트 종류" value={settings.overlay || !candleAvailable ? "line" : settings.kind} disabled={settings.overlay} onChange={event => patch({ kind: event.target.value as Settings["kind"] })}><option value="line">선</option><option value="candles" disabled={!candleAvailable}>캔들 (OHLC 제공 종목)</option></select></label>
      <label><input type="checkbox" checked={settings.average} disabled={settings.overlay} onChange={event => patch({ average: event.target.checked })} />MA 20</label>
      <label><input type="checkbox" checked={settings.volume} disabled={settings.overlay} onChange={event => patch({ volume: event.target.checked })} />거래량</label>
      <label><input type="checkbox" checked={settings.logarithmic} disabled={settings.overlay} onChange={event => patch({ logarithmic: event.target.checked })} />로그 축</label>
      <button type="button" onClick={() => setFit(value => value + 1)}>화면 맞춤</button>
    </div>
    <div className="replaySelections">{settings.selections.map((selection, index) => <SelectionEditor key={index} selection={selection} index={index} onApply={value => select(index, value)} />)}</div>
    {(peerStatus || settings.peerReason) && <p className="replayNotice" role="status" data-peer-reason>{peerStatus || `비교 종목 선정: ${settings.peerReason}`}</p>}
    <div className="replayPreset"><button type="button" onClick={() => { setPlaying(false); patch({ selections: REPLAY_PRESET.map(row => ({ ...row })), count: 25, autoPeer: false, peerReason: undefined }); setPeerStatus(""); setFit(value => value + 1); }}>예시: 코스피 2022 ↔ 금 2024</button><span>각 시장의 첫 거래일부터 경과 거래일 수를 맞춥니다.</span></div>
    <div className="replayTransport" role="group" aria-label="리플레이 재생 제어">
      <button type="button" disabled={!ready} onClick={() => { setPlaying(false); patch({ count: 1 }); }} aria-label="리플레이 처음으로">↤ 처음</button>
      <button type="button" disabled={!ready || count <= 1} onClick={() => { setPlaying(false); patch({ count: count - 1 }); }} aria-label="리플레이 이전 봉">이전 봉</button>
      <button type="button" className="replayPlay" disabled={!ready} aria-pressed={playing} onClick={() => { if (count >= maximum) patch({ count: 1 }); setPlaying(value => !value); }}>{playing ? "일시정지" : "재생"}</button>
      <button type="button" disabled={!ready || count >= maximum} onClick={() => { setPlaying(false); patch({ count: count + 1 }); }} aria-label="리플레이 다음 봉">다음 봉</button>
      <label>속도<select aria-label="리플레이 속도" value={settings.speed} onChange={event => patch({ speed: Number(event.target.value) })}>{[1, 2, 5, 10].map(speed => <option value={speed} key={speed}>{speed}봉/초</option>)}</select></label>
      <output aria-label="리플레이 진행" data-replay-count={count} data-replay-max={maximum}>{ready ? `${count} / ${maximum} 거래일` : "자료 확인 중"}</output>
      <input type="range" min={1} max={maximum} value={count} disabled={!ready} aria-label="리플레이 위치" onChange={event => { setPlaying(false); patch({ count: Number(event.target.value) }); }} />
      <button type="button" disabled={!ready || count >= maximum} onClick={() => { setPlaying(false); patch({ count: maximum }); }}>끝으로</button>
    </div>
    {notice && <p className="replayNotice" role="status">{notice}</p>}
    <div className="replayReadouts">{[first, second].map((row, index) => {
      const visible = ranges[index].slice(0, ready ? count : 0), bar = visible.at(-1), change = replayReturns(visible).at(-1)?.value;
      return <div key={index} className={`replayReadout replayReadout${index}`} data-replay-series={index} data-visible-bars={visible.length} data-visible-date={bar?.date ?? ""}>
        <div><strong>{index === 0 ? "A" : "B"} · {settings.selections[index].name}</strong><span>{settings.selections[index].ticker}</span></div>
        {row.loading || index === 1 && peerPending ? <p role="status">{index === 1 && peerPending ? "비슷한 종목을 확인하고 있습니다…" : "저장된 가격을 불러오는 중…"}</p> : errors[index] ? <p role="alert">{errors[index]} {settings.selections[index].ticker && <button type="button" onClick={() => setRetry(values => values.map((v, i) => i === index ? v + 1 : v))}>다시 조회</button>}</p> : <>
          <div className="replayReadoutValue"><time>{bar?.date ?? "—"}</time><strong>{bar?.close.toLocaleString("ko-KR", { maximumFractionDigits: 2 }) ?? "—"} <small>{row.market?.ticker === "^KS11" ? "pt" : row.market?.currency}</small></strong><span className={change !== undefined && change < 0 ? "negative" : "positive"}>{change === undefined ? "—" : `${change >= 0 ? "+" : ""}${change.toFixed(2)}%`}</span></div>
          {bar && hasOHLC(bar) && <p className="replayOHLC">시 {bar.open!.toFixed(2)} · 고 {bar.high!.toFixed(2)} · 저 {bar.low!.toFixed(2)} · 종 {bar.close.toFixed(2)}</p>}
        </>}
        {row.market && <p className="replaySource">제공 범위 {row.market.bars[0].date} ~ {row.market.bars.at(-1)!.date} · {row.market.source}{row.market.bars.every(hasOHLC) ? " · 실제 OHLC" : " · 종가 자료"}</p>}
      </div>;
    })}</div>
    <ReplayCharts markets={markets} ranges={ready ? ranges : [[], []]} count={ready ? count : 0} overlay={settings.overlay} kind={candleAvailable ? settings.kind : "line"} interval={settings.interval} average={settings.average} volume={settings.volume} logarithmic={settings.logarithmic} fit={fit} />
    <p className="replayFootnote">하루에 한 거래일씩 공개합니다. 주·월봉과 MA 20은 공개된 일봉으로만 계산하며, 두 기간 중 짧은 쪽의 마지막 거래일에서 함께 멈춥니다. 수익률은 각 기간 첫 수정종가 기준이며 환율은 반영하지 않습니다.{settings.selections.some(row => row.ticker === "GC=F") && " 금은 현물이 아닌 GC=F 연속선물로 계약 교체의 영향을 받습니다."}</p>
    {settings.overlay && <p className="replayFootnote">수익률 겹쳐 보기는 일봉 기준입니다. 가로축의 1봉은 각 기간의 첫 거래일입니다.</p>}
  </section>;
}

function SelectionEditor({ selection, index, onApply }: { selection: ReplaySelection; index: number; onApply: (value: ReplaySelection) => void }) {
  const [query, setQuery] = useState(selection.ticker), [start, setStart] = useState(selection.start), [end, setEnd] = useState(selection.end);
  const [symbols, setSymbols] = useState<ChartSymbol[]>([]), [error, setError] = useState("");
  const [open, setOpen] = useState(false), [highlighted, setHighlighted] = useState(0), [applying, setApplying] = useState(false);
  const id = useId(), alive = useRef(true), requested = useRef(false);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  useEffect(() => { setQuery(selection.ticker); setStart(selection.start); setEnd(selection.end); setError(""); setOpen(false); }, [selection]);
  const catalog = [...new Map([...BUILTINS, selection, ...symbols].map(row => [row.ticker, row])).values()];
  const matches = searchChartSymbols(catalog, query, []);
  function choose(symbol: ChartSymbol) { setQuery(symbol.ticker); setError(""); setOpen(false); }
  function loadCatalog() {
    if (requested.current) return;
    requested.current = true;
    void getChartSymbols().then(rows => { if (alive.current) setSymbols(rows); }).catch(() => { requested.current = false; if (alive.current) setError("종목 목록을 불러오지 못했습니다. 티커를 직접 입력하거나 다시 선택해 주세요."); });
  }
  async function apply() {
    if (!validReplayDate(start) || !validReplayDate(end) || start > end) { setError("시작일은 종료일보다 늦을 수 없습니다. 날짜를 확인해 주세요."); return; }
    const text = query.trim(), validTicker = /^[A-Z0-9^][A-Z0-9.^:_=\-]{0,39}$/.test(text.toUpperCase());
    const exactMatch = (row: ChartSymbol) => row.ticker.toUpperCase() === text.toUpperCase() || row.name.toLocaleLowerCase() === text.toLocaleLowerCase() || (row.ticker === "GC=F" && text === "금");
    let rows = catalog;
    // Submitting a name immediately after focus must also wait for the catalog.
    if (!validTicker && !rows.some(exactMatch)) {
      setApplying(true);
      try { const loaded = await getChartSymbols(); rows = [...new Map([...catalog, ...loaded].map(row => [row.ticker, row])).values()]; if (alive.current) setSymbols(loaded); }
      catch { /* Built-in market names remain available without the catalog. */ }
      finally { if (alive.current) setApplying(false); }
      if (!alive.current) return;
    }
    const exact = rows.find(exactMatch);
    const candidates = searchChartSymbols(rows, text, []);
    const symbol = exact ?? (!validTicker && candidates.length === 1 ? candidates[0] : undefined);
    if (!symbol && !validTicker) { setError("검색 목록에서 종목을 선택하거나 올바른 티커를 입력해 주세요."); setOpen(true); return; }
    setError(""); setOpen(false); onApply({ ticker: symbol?.ticker ?? text.toUpperCase(), name: symbol?.name ?? text.toUpperCase(), exchange: symbol?.exchange, start, end });
  }
  return <form className="replaySelection" aria-label={`차트 ${index === 0 ? "A" : "B"} 기간 설정`} onSubmit={event => { event.preventDefault(); apply(); }}>
    <span className={`replayBadge replayBadge${index}`}>{index === 0 ? "A" : "B"}</span>
    <div className="replaySymbolInput" onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false); }}>
      <label>종목 <ImeSearchInput aria-label={`차트 ${index === 0 ? "A" : "B"} 종목`} role="combobox" aria-expanded={open && matches.length > 0} aria-controls={`${id}-symbols`} aria-autocomplete="list" aria-activedescendant={open && matches[highlighted] ? `${id}-symbol-${highlighted}` : undefined} value={query} onValueChange={value => { setQuery(value); setHighlighted(0); setOpen(true); setError(""); }} onFocus={() => { loadCatalog(); setOpen(true); }} onKeyDown={event => {
        if (event.nativeEvent.isComposing || event.keyCode === 229) { if (event.key === "Enter") event.preventDefault(); return; }
        if (event.key === "Escape") { event.preventDefault(); setOpen(false); }
        if (open && matches.length) {
          if (event.key === "ArrowDown" || event.key === "ArrowUp") { event.preventDefault(); setHighlighted(value => (value + (event.key === "ArrowDown" ? 1 : -1) + matches.length) % matches.length); }
          if (event.key === "Enter") { event.preventDefault(); choose(matches[Math.min(highlighted, matches.length - 1)]); }
        }
      }} placeholder="코스피, 금 또는 종목명·티커" autoComplete="off" /></label>
      {open && matches.length > 0 && <div id={`${id}-symbols`} className="replaySearchResults" role="listbox" aria-label={`차트 ${index === 0 ? "A" : "B"} 종목 검색 결과`}>{matches.map((row, i) => <button type="button" role="option" aria-selected={highlighted === i} id={`${id}-symbol-${i}`} key={row.ticker} onMouseDown={event => event.preventDefault()} onClick={() => choose(row)}><strong>{row.name}</strong><span>{row.ticker}{row.exchange ? ` · ${row.exchange}` : ""}</span></button>)}</div>}
    </div>
    <label>시작일<input aria-label={`차트 ${index === 0 ? "A" : "B"} 시작일`} type="date" value={start} required onChange={event => setStart(event.target.value)} /></label>
    <label>종료일<input aria-label={`차트 ${index === 0 ? "A" : "B"} 종료일`} type="date" value={end} required onChange={event => setEnd(event.target.value)} /></label>
    <button type="submit" disabled={applying}>{applying ? "확인 중…" : "적용"}</button>{error && <p className="replaySelectionError" role="alert">{error}</p>}
  </form>;
}
