import { useEffect, useId, useRef, useState } from "react";
import type { ReactNode } from "react";
import { TradingViewWidget } from "./TradingViewWidget";
import { tradingViewSymbol } from "../dataClient/stockDetailLinks";
import { tradingViewChartUrl, tradingViewWidgetRestricted } from "../dataClient/tradingViewChart";
import { getStockInformation } from "../dataClient/stockInformationClient";

export function StockChartTabs({ ticker, name, exchange, children }: { ticker: string; name: string; exchange?: string; children: ReactNode }) {
  const [view, setView] = useState<"tradingview" | "archive">(() => tradingViewWidgetRestricted(tradingViewSymbol(ticker, exchange)) ? "archive" : "tradingview");
  const [symbol, setSymbol] = useState<string | null>(() => tradingViewSymbol(ticker, exchange));
  const [resolving, setResolving] = useState(!symbol), [expanded, setExpanded] = useState(false);
  const panel = useRef<HTMLElement>(null), id = useId();
  useEffect(() => {
    if (symbol) return;
    const controller = new AbortController();
    void getStockInformation(ticker, exchange, controller.signal).then(info => {
      const source = info.source_symbol?.toUpperCase();
      if (!controller.signal.aborted && source && tradingViewSymbol(ticker, source.split(":")[0]) === source) { setSymbol(source); if (tradingViewWidgetRestricted(source)) setView("archive"); }
    }).catch(() => {}).finally(() => { if (!controller.signal.aborted) setResolving(false); });
    return () => controller.abort();
  }, [ticker, exchange, symbol]);
  useEffect(() => {
    if (!expanded) return;
    const previous = document.activeElement as HTMLElement | null, overflow = document.body.style.overflow;
    const keydown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setExpanded(false);
      if (event.key === "Tab") {
        const controls = panel.current?.querySelectorAll<HTMLElement>('a[href],button:not([disabled]),iframe');
        const first = controls?.[0], last = controls?.[controls.length - 1];
        if (event.shiftKey && (document.activeElement === first || document.activeElement === panel.current)) { event.preventDefault(); last?.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
      }
    };
    document.body.style.overflow = "hidden"; document.addEventListener("keydown", keydown); panel.current?.focus();
    return () => { document.body.style.overflow = overflow; document.removeEventListener("keydown", keydown); if (previous?.isConnected) previous.focus(); };
  }, [expanded]);
  return <div className="stockChartTabs">
    <div className="stockChartViewNavigation"><div className="stockChartViewTabs" role="tablist" aria-label="종목 차트 선택">{([["tradingview", "TradingView 차트"], ["archive", "저장 일봉·분석"]] as const).map(([value, label]) => <button key={value} type="button" role="tab" id={`${id}-${value}-tab`} aria-selected={view === value} aria-controls={`${id}-${value}`} data-chart-view={value} onClick={() => setView(value)}>{label}</button>)}</div><a className="fullTradingViewLink" href={tradingViewChartUrl(symbol ?? ticker)} target="_blank" rel="noopener noreferrer">TradingView 전체 기능 ↗</a></div>
    <div id={`${id}-tradingview`} role="tabpanel" aria-labelledby={`${id}-tradingview-tab`} hidden={view !== "tradingview"}>
      <section ref={panel} tabIndex={-1} className={`semiPanel officialStockChart${expanded ? " tvExpanded" : ""}`} role={expanded ? "dialog" : undefined} aria-modal={expanded ? true : undefined} aria-label={expanded ? `${name} TradingView 차트` : undefined}>
        <div className="officialChartHeading"><div><h2>TradingView</h2><p>{name} · {symbol ?? ticker}</p></div><div className="officialChartActions"><button type="button" aria-pressed={expanded} onClick={() => setExpanded(value => !value)}>{expanded ? "크게 보기 닫기" : "크게 보기"}</button><a href={tradingViewChartUrl(symbol ?? ticker)} target="_blank" rel="noopener noreferrer">TradingView 전체 화면 ↗</a></div></div>
        <p className="officialChartGuide">상단에서 종목 비교·차트 종류·시간 간격·지표를, 왼쪽에서 추세선·평행 채널·피보나치·측정 도구를 선택하세요.</p>
        {tradingViewWidgetRestricted(symbol) ? <div className="officialChartUnavailable" role="status"><strong>이 종목은 TradingView에서 직접 열어 분석할 수 있습니다.</strong><p>KRX 종목은 TradingView의 외부 차트 표시가 제한됩니다. 전체 기능 버튼으로 같은 종목을 열거나 저장 일봉·분석 탭을 이용하세요.</p><a href={tradingViewChartUrl(symbol!)} target="_blank" rel="noopener noreferrer">이 종목을 TradingView에서 분석 ↗</a></div> : symbol ? <TradingViewWidget symbol={symbol} kind="chart" /> : <div className="officialChartUnavailable" role="status">{resolving ? "TradingView 거래소 정보를 확인하고 있습니다…" : "이 종목의 TradingView 거래소를 확인하지 못했습니다. 전체 화면에서 종목을 검색하거나 저장 일봉·분석을 이용해 주세요."}</div>}
        <p className="officialChartNote">종목에 따라 외부 차트 표시가 제한될 수 있습니다. 그런 경우 ‘TradingView 전체 화면’에서 확인할 수 있습니다. Pine·알림·전략 테스트는 TradingView에서 이용하세요.</p>
      </section>
    </div>
    <div id={`${id}-archive`} role="tabpanel" aria-labelledby={`${id}-archive-tab`} hidden={view !== "archive"}>{children}</div>
  </div>;
}
