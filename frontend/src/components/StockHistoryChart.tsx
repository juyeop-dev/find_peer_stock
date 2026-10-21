import { useCallback, useEffect, useMemo, useState } from "react";
import { SemiconductorLineChart } from "./SemiconductorLineChart";
import { ErrorNotice } from "./ErrorNotice";
import { LoadingSpinner } from "./LoadingSpinner";
import { usePollingData } from "../dataClient/usePollingData";
import { CHART_PERIODS, chartPeriodLabel, chartStart, getStockHistory, historyRange, yearCovered } from "../dataClient/stockHistoryClient";
import type { ChartPeriod, StockHistory } from "../dataClient/stockHistoryClient";
import type { SemiconductorPrice } from "../dataClient/semiconductorTypes";
import { formatPercent } from "../dataClient/semiconductorMath";

interface Props {
  ticker: string; name: string; exchange?: string; currency?: string; history?: SemiconductorPrice[];
  source?: string; generatedAt?: string; refreshKey?: string;
}
export function StockHistoryChart({ ticker, name, exchange, currency, history, source, generatedAt, refreshKey }: Props) {
  const [period, setPeriod] = useState<ChartPeriod>("1y");
  const [cached, setCached] = useState<StockHistory>();
  useEffect(() => { setPeriod("1y"); }, [ticker]);
  const initial = useMemo<StockHistory | undefined>(() => history?.length ? ({ ticker, currency: currency ?? "KRW", source: source ?? "일별 가격 원본", fetched_at: generatedAt, history }) : undefined,
    [ticker, currency, source, generatedAt, history]);
  const load = useCallback((signal: AbortSignal, fromSource = false) => getStockHistory(ticker, exchange, signal, fromSource, initial, setCached), [ticker, exchange, initial, refreshKey]);
  const { data, loading, refreshing, error, refresh } = usePollingData(load, 300000);
  const shown = data?.ticker.toUpperCase() === ticker.toUpperCase() ? data : cached?.ticker.toUpperCase() === ticker.toUpperCase() ? cached : initial;
  const daily = shown?.history ?? [];
  const points = historyRange(daily, period);
  const latest = daily.at(-1);
  const oldHistory = Boolean(latest && Date.now() - Date.parse(`${latest.date}T23:59:59Z`) >= 7 * 86400000);
  const covered = yearCovered(daily);
  const shortListing = Boolean(shown?.first_trade_date && latest && shown.first_trade_date > chartStart(latest.date, "1y"));
  const startCovered = latest && points[0] && points[0].date <= chartStart(latest.date, period);
  const gain = startCovered && points[0].adjusted_close > 0 ? (points.at(-1)!.adjusted_close / points[0].adjusted_close - 1) * 100 : null;
  return <section className="semiPanel semiChartPanel stockHistoryChart">
    <div className="semiPanelHeading semiHeadingSplit"><div><h2>주가 차트</h2><p>{oldHistory ? `${latest!.date} 기준 ` : ""}{period === "since2024H2" ? "2024년 7월 1일부터" : period === "since2025" ? "2025년 1월 1일부터" : `최근 ${chartPeriodLabel(period)}`} · 일별 종가</p></div>
      <div className="semiPeriodTabs" aria-label="주가 차트 기간">{CHART_PERIODS.map(value => <button key={value} type="button" className={period === value ? "active" : ""} onClick={() => setPeriod(value)}>{chartPeriodLabel(value)}</button>)}</div>
    </div>
    {loading && !daily.length ? <LoadingSpinner /> : null}
    {error ? <ErrorNotice message={error} /> : null}
    {data?.warning ? <p className="semiFootnote" role="status">{data.warning}</p> : null}
    {shown?.source.includes("Cboe One") ? <p className="semiFootnote" role="status">미국 Cboe One의 대체 거래 자료입니다. 주 거래소의 종가와 다를 수 있습니다.</p> : null}
    {oldHistory ? <p className="semiFootnote" role="status">제공처의 최근 일봉은 {latest!.date}입니다. 이후 제공되지 않은 가격은 채우지 않습니다.</p> : null}
    {daily.length > 0 && !covered ? <p className="semiFootnote" role="status">{shortListing ? `제공 이력은 1년 미만입니다. 최초 거래일: ${shown?.first_trade_date}` : "최근 1년 전체 이력이 부족합니다. 제공처에서 확인된 날짜만 표시합니다."}</p> : null}
    {(period === "since2025" || period === "since2024H2") && latest && points.length > 0 && points[0].date > chartStart(latest.date, period) ? <p className="semiFootnote" role="status">선택한 시작일까지의 일봉을 확인하지 못했습니다. 실제 제공 시작일 {points[0].date}부터 표시합니다.</p> : null}
    <SemiconductorLineChart points={points.map(point => ({ date: point.date, value: point.close }))} title={`${name} 주가`} unit={(shown?.currency ?? currency) === "KRW" ? "원" : shown?.currency ?? currency ?? ""} />
    <div className="semiReturnSummary"><span>{chartPeriodLabel(period)} 수익률</span><strong className={(gain ?? 0) >= 0 ? "semiUp" : "semiDown"}>{formatPercent(gain)}</strong></div>
    {points.length ? <p className="semiFootnote">{points[0].date} ~ {points.at(-1)!.date} · {points.length}개 거래일 · {shown?.source ?? source} · 실제 제공된 일봉 기준. 수익률은 조정 종가가 제공되면 이를 사용하고, 없으면 제공 종가 기준입니다.</p> : null}
    <button type="button" className="semiTextButton" disabled={refreshing} onClick={refresh}>{refreshing ? "일봉 조회 중…" : "일봉 다시 조회"}</button>
  </section>;
}
