import { useEffect, useRef } from "react";
import { CandlestickSeries, ColorType, createChart, HistogramSeries, LineSeries, PriceScaleMode } from "lightweight-charts";
import type { IChartApi, LogicalRange, Time, UTCTimestamp } from "lightweight-charts";
import { aggregateReplay, hasOHLC, replayAverage, replayReturns } from "../dataClient/chartReplay";
import type { ReplayBar, ReplayInterval, ReplayMarket } from "../dataClient/chartReplay";

interface Props {
  markets: (ReplayMarket | undefined)[]; ranges: ReplayBar[][]; count: number;
  overlay: boolean; kind: "line" | "candles"; interval: ReplayInterval;
  average: boolean; volume: boolean; logarithmic: boolean; fit: number;
}
const COLORS = ["#137d87", "#bd8526"];
// The overlay uses a synthetic time axis solely to align session numbers.
// Tooltips and tick labels expose the session count, never a synthetic date.
const sessionTime = (session: number) => (946684800 + session * 86400) as UTCTimestamp;

export function ReplayCharts(props: Props) {
  const hosts = useRef<(HTMLDivElement | null)[]>([]), charts = useRef<IChartApi[]>([]);
  const update = useRef<(value: Props) => void>(() => {}), current = useRef(props);
  current.current = props;
  const { overlay, kind, interval, average, volume, logarithmic, fit } = props;
  useEffect(() => {
    const instances: IChartApi[] = [];
    const renderers: ((p: Props) => void)[] = [];
    const crosshairTargets: ((index: number | null) => void)[] = [];
    for (let panel = 0; panel < (overlay ? 1 : 2); panel++) {
      const host = hosts.current[panel];
      if (!host) continue;
      const chart = createChart(host, {
        autoSize: true, height: 330,
        layout: { background: { type: ColorType.Solid, color: "#ffffff" }, textColor: "#586b7b", fontFamily: "system-ui, sans-serif", attributionLogo: true },
        grid: { vertLines: { color: "#edf2f5" }, horzLines: { color: "#edf2f5" } },
        rightPriceScale: { mode: overlay ? PriceScaleMode.Normal : logarithmic ? PriceScaleMode.Logarithmic : PriceScaleMode.Normal, scaleMargins: { top: .13, bottom: volume && !overlay ? .24 : .1 } },
        timeScale: { borderColor: "#dce5e9", ...(overlay ? { tickMarkFormatter: (time: Time) => `${Math.round((Number(time) - 946684800) / 86400) + 1}봉` } : {}) },
        ...(overlay ? { localization: { timeFormatter: (time: Time) => `경과 ${Math.round((Number(time) - 946684800) / 86400) + 1}봉` } } : {}),
      });
      instances.push(chart);
      const indexes = overlay ? [0, 1] : [panel];
      for (const index of indexes) {
        const candle = !overlay && kind === "candles";
        const line = candle ? undefined : chart.addSeries(LineSeries, { color: COLORS[index], lineWidth: 2, ...(overlay ? { priceFormat: { type: "custom", minMove: .01, formatter: (value: number) => `${value.toFixed(2)}%` } } : {}) });
        const candles = candle ? chart.addSeries(CandlestickSeries, { upColor: "#d45656", downColor: "#4387b5", wickUpColor: "#d45656", wickDownColor: "#4387b5", borderVisible: false }) : undefined;
        const ma = average && !overlay ? chart.addSeries(LineSeries, { color: "#9862c6", lineWidth: 1, priceLineVisible: false, lastValueVisible: false }) : undefined;
        const histogram = volume && !overlay ? chart.addSeries(HistogramSeries, { priceFormat: { type: "volume" }, priceScaleId: "volume", priceLineVisible: false, lastValueVisible: false }) : undefined;
        if (histogram) histogram.priceScale().applyOptions({ scaleMargins: { top: .83, bottom: 0 }, visible: false });
        renderers.push(p => {
          const visible = p.ranges[index]?.slice(0, p.count) ?? [];
          const bars = aggregateReplay(visible, p.interval);
          if (line) line.setData(overlay ? replayReturns(visible).map((point, i) => ({ time: sessionTime(i), value: point.value })) : bars.map(bar => ({ time: bar.date, value: bar.close })));
          if (candles) candles.setData(bars.filter(hasOHLC).map(bar => ({ time: bar.date, open: bar.open!, high: bar.high!, low: bar.low!, close: bar.close })));
          if (ma) ma.setData(replayAverage(bars, 20).map(point => ({ time: point.date, value: point.value })));
          if (histogram) histogram.setData(bars.filter(bar => bar.volume !== null).map(bar => ({ time: bar.date, value: bar.volume!, color: bar.close >= (bar.open ?? bar.close) ? "#d456564d" : "#4387b54d" })));
        });
        if (!overlay) crosshairTargets.push(logical => {
          const p = current.current, bar = logical === null ? undefined : aggregateReplay(p.ranges[index]?.slice(0, p.count) ?? [], p.interval)[logical];
          if (bar) chart.setCrosshairPosition(bar.close, bar.date, (line ?? candles)!);
          else chart.clearCrosshairPosition();
        });
      }
    }
    charts.current = instances;
    let synchronizing = false;
    if (!overlay && instances.length === 2) instances.forEach((chart, index) => {
      chart.timeScale().subscribeVisibleLogicalRangeChange((range: LogicalRange | null) => {
        if (!range || synchronizing) return;
        synchronizing = true;
        try { instances[1 - index].timeScale().setVisibleLogicalRange(range); } finally { synchronizing = false; }
      });
      chart.subscribeCrosshairMove(param => {
        if (synchronizing) return;
        synchronizing = true;
        try { crosshairTargets[1 - index]?.(param.point && param.logical !== undefined ? Math.round(Number(param.logical)) : null); } finally { synchronizing = false; }
      });
    });
    update.current = value => { renderers.forEach(render => render(value)); };
    update.current(current.current);
    instances.forEach(chart => chart.timeScale().fitContent());
    return () => { update.current = () => {}; charts.current = []; instances.forEach(chart => chart.remove()); };
  }, [overlay, kind, interval, average, volume, logarithmic]);
  useEffect(() => {
    update.current(props);
    // Follow newly revealed bars while preserving user zoom. Seeking backwards
    // resets to the available window so no hidden future space is implied.
    charts.current.forEach(chart => chart.timeScale().scrollToRealTime());
  }, [props.ranges, props.count, props.markets]);
  useEffect(() => { charts.current.forEach(chart => chart.timeScale().fitContent()); }, [props.ranges]);
  useEffect(() => { charts.current.forEach(chart => chart.timeScale().fitContent()); }, [fit]);

  function download() {
    const images = charts.current.map(chart => chart.takeScreenshot());
    if (!images.length) return;
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(...images.map(img => img.width)); canvas.height = images.reduce((sum, img) => sum + img.height, 0);
    const ctx = canvas.getContext("2d"); if (!ctx) return;
    let top = 0; for (const img of images) { ctx.drawImage(img, 0, top); top += img.height; }
    canvas.toBlob(blob => { if (!blob) return; const url = URL.createObjectURL(blob), link = document.createElement("a"); link.href = url; link.download = "stock-peer-replay.png"; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); });
  }
  return <>
    <div className={`replayPlots ${overlay ? "isOverlay" : ""}`}>
      {(overlay ? [0] : [0, 1]).map(index => <div className="replayPlotPanel" key={index}>
        <div className="replayPlotHeading">{overlay ? "수익률 비교 · 각 기간 첫 수정종가 = 0%" : `${props.markets[index]?.name ?? (index === 0 ? "차트 A" : "차트 B")} · ${props.markets[index]?.ticker === "^KS11" ? "pt" : props.markets[index]?.currency ?? ""}`}<span>{overlay ? "같은 경과 거래일끼리 정렬" : "휠로 확대 · 드래그로 이동"}</span></div>
        <div ref={node => { hosts.current[index] = node; }} className="replayCanvas" role="img" aria-label={overlay ? "경과 봉 수 기준 수익률 비교 차트" : `${props.markets[index]?.name ?? "조회 중"} 리플레이 차트`} />
      </div>)}
    </div>
    <div className="replayCanvasFooter"><span>차트: <a href="https://www.tradingview.com/" target="_blank" rel="noopener noreferrer">TradingView Lightweight Charts™</a> · Copyright (c) 2025 TradingView, Inc. · Apache 2.0</span><button type="button" onClick={download}>차트 이미지 저장</button></div>
  </>;
}
