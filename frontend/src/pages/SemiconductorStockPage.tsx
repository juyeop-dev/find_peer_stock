import { useCallback } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { StockHistoryChart } from "../components/StockHistoryChart";
import { DataRefreshStatus } from "../components/DataRefreshStatus";
import { ErrorNotice } from "../components/ErrorNotice";
import { LoadingSpinner } from "../components/LoadingSpinner";
import { RecentFinancialSummary } from "../components/RecentFinancials";
import { formatDateTime } from "../dataClient/formatters";
import { effectiveHistory, formatEok, formatPercent, formatWon } from "../dataClient/semiconductorMath";
import { stockClassifications } from "../dataClient/semiconductorTypes";
import type { SemiconductorData, SemiconductorFinancial } from "../dataClient/semiconductorTypes";
import { getSemiconductorData } from "../dataClient/staticStockDataClient";
import { usePollingData } from "../dataClient/usePollingData";
import { calendarReturnLink } from "../dataClient/stockDetailLinks";

const METRICS: [string, string][] = [
  ["marketValue", "시가총액"], ["per", "PER"], ["pbr", "PBR"], ["eps", "EPS"],
  ["bps", "BPS"], ["dividendYieldRatio", "배당수익률"],
  ["highPriceOf52Weeks", "52주 최고"], ["lowPriceOf52Weeks", "52주 최저"],
];

export function FinancialTable({ title, rows }: { title: string; rows: SemiconductorFinancial[] }) {
  return <div className="semiFinanceBlock"><h3>{title}</h3>
    {rows.length ? <div className="semiTableWrap"><table className="semiTable"><thead><tr><th>기간</th><th>매출</th><th>영업이익</th><th>순이익</th></tr></thead><tbody>
      {rows.map((row) => <tr key={`${row.type}-${row.period}`}><td>{row.period}</td><td className="semiNumber">{formatEok(row.revenue)}</td><td className="semiNumber">{formatEok(row.operating_income)}</td><td className="semiNumber">{formatEok(row.net_income)}</td></tr>)}
    </tbody></table></div> : <p className="semiEmpty">확정 재무 정보가 없습니다.</p>}</div>;
}

export function SemiconductorStockPage() {
  const { ticker = "" } = useParams();
  const [params] = useSearchParams();
  const returnTo = params.get("returnTo") ? calendarReturnLink(params.get("returnTo")) : null;
  const loadData = useCallback((signal: AbortSignal, fromSource = false, current?: SemiconductorData | null) => getSemiconductorData(signal, fromSource, current, [ticker]), [ticker]);
  const { data, error, loading, refreshing, lastCheckedAt, lastSourceAt, refresh } = usePollingData(loadData, 300_000);
  const stock = data?.stocks.find((item) => item.ticker === ticker);
  const history = stock ? effectiveHistory(stock) : [];
  const latest = history.at(-1);
  const quote = stock?.quote;
  const currentPrice = quote?.price ?? latest?.close ?? null;

  return <main className="pageShell semiPage">
    {returnTo ? <div className="semiBreadcrumb"><Link to={returnTo}>← {returnTo.startsWith("/turnover") ? "거래대금 캘린더" : returnTo.startsWith("/calendar-history") ? "누적 기록" : "신고가 캘린더"}로 돌아가기</Link></div> : null}
    <div className="semiBreadcrumb"><Link to="/semiconductors">반도체 종목</Link><span>/</span><span>{stock?.name ?? ticker}</span></div>
    <DataRefreshStatus refreshing={refreshing} lastCheckedAt={lastCheckedAt} lastSourceAt={lastSourceAt} generatedAt={data?.quoted_at} cadence="semiconductor" onRefresh={refresh} />
    {loading && <LoadingSpinner />}{error && <ErrorNotice message={error} />}
    {data && !stock && <ErrorNotice message="반도체 분류에 등록된 종목이 아닙니다." />}
    {stock && <>
      <header className="semiDetailHeader"><div><p className="eyebrow">{stock.major} / {stock.middle} / {stock.minor}</p><h1>{stock.name}</h1>
        <p>{stock.market} · {stock.code} · {stock.ticker}</p></div>
        <div className="semiQuoteHero"><span>현재가 / 최근 제공 가격</span><strong>{formatWon(currentPrice)}</strong>
          <b className={(quote?.change_pct ?? 0) >= 0 ? "semiUp" : "semiDown"}>{formatPercent(quote?.change_pct)}</b>
          <small>{quote?.status === "stale" ? "이전 종가 · " : ""}제공처 기준 {quote?.provider_time?.replace("T", " ").slice(0, 16) ?? latest?.date ?? "-"}</small></div></header>
      <section className="semiPanel semiMembershipPanel"><div className="semiPanelHeading"><h2>소속 섹터</h2><p>이미지와 기업 사업 자료를 바탕으로 산업 분류와 연관 테마를 함께 표시합니다.</p></div>
        <div className="semiMemberships">{stockClassifications(stock).map((item) => <span key={`${item.major}/${item.middle}/${item.minor}`} className={item.major === "핵심 연관 테마" ? "theme" : ""}>
          <small>{item.major} / {item.middle}</small><strong>{item.minor}</strong></span>)}</div>
      </section>
      {stock.business_summary && <section className="semiPanel semiBusinessPanel"><div className="semiPanelHeading"><h2>반도체 사업</h2></div>
        <p>{stock.business_summary}</p>
        {Boolean(stock.business_sources?.length) && <div className="semiBusinessSources">{stock.business_sources!.map((source) =>
          <a key={source.url} href={source.url} target="_blank" rel="noreferrer">{source.label} ↗</a>)}</div>}
      </section>}
      <div className="semiDetailGrid">
        <StockHistoryChart ticker={stock.ticker} name={stock.name} exchange={stock.market} currency="KRW" history={stock.history} source={data?.history_source} generatedAt={data?.generated_at} refreshKey={stock.quote.fetched_at} />
        <section className="semiPanel semiMetricsPanel"><div className="semiPanelHeading"><h2>종목 기본 정보</h2><p>투자 지표는 Naver Finance 제공 값입니다.</p></div>
          <dl>{METRICS.map(([key, label]) => <div key={key}><dt>{label}</dt><dd>{stock.metrics[key] || "-"}</dd></div>)}</dl>
        </section>
      </div>
      <section className="semiPanel"><div className="semiPanelHeading"><h2>실적</h2><p>확정 실적만 표시 · 단위: 억원 · 매출/영업이익/당기순이익</p></div>
        <RecentFinancialSummary summary={stock.recent_financials} />
        <div className="semiFinanceGrid"><FinancialTable title="연간" rows={stock.annual_financials} /><FinancialTable title="분기" rows={stock.quarterly_financials} /></div>
      </section>
      <section className="semiPanel"><div className="semiPanelHeading"><h2>최근 일별 가격</h2><p>차트 데이터 기준 · 거래일별 종가와 거래량</p></div>
        <div className="semiTableWrap"><table className="semiTable"><thead><tr><th>날짜</th><th>종가</th><th>거래량</th></tr></thead><tbody>
          {[...history].reverse().slice(0, 20).map((point) => <tr key={point.date}><td>{point.date}</td><td className="semiNumber">{formatWon(point.close)}</td><td className="semiNumber">{point.volume?.toLocaleString("ko-KR") ?? "-"}</td></tr>)}
        </tbody></table></div>
      </section>
      <p className="semiFootnote">주가: <a href={`https://finance.yahoo.com/quote/${encodeURIComponent(stock.ticker)}/`} target="_blank" rel="noreferrer">Yahoo Finance</a> 일봉, 누락된 최근 거래일은 <a href={`https://m.stock.naver.com/domestic/stock/${stock.code}/total`} target="_blank" rel="noreferrer">Naver Finance</a> 일봉으로 보완. 현재가/투자 지표/실적도 Naver Finance 자료입니다. 실적 수집 {formatDateTime(data?.generated_at ?? null)}, 현재가 수집 {formatDateTime(data?.quoted_at ?? null)}. 수익률 계산에는 분할·배당 조정 종가를 사용합니다. 산업 구조와 연관 테마 분류는 제공 이미지 및 기업 공식 사업 자료 기준입니다.</p>
    </>}
  </main>;
}
