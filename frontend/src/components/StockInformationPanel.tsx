import { useCallback } from "react";
import { getStockInformation } from "../dataClient/stockInformationClient";
import type { StockStatement } from "../dataClient/stockInformationClient";
import { usePollingData } from "../dataClient/usePollingData";
import { ErrorNotice } from "./ErrorNotice";
import { formatDateTime, formatMarketCap } from "../dataClient/formatters";

const amount = (value?: number | null) => value == null ? "—" : new Intl.NumberFormat("ko-KR", {maximumFractionDigits: 2, notation: "compact"}).format(value);
const priceText = (value: number) => new Intl.NumberFormat("ko-KR", {maximumFractionDigits: Math.abs(value) < 0.01 ? 8 : Math.abs(value) < 1 ? 4 : 2}).format(value);
const labels = {annual: "연간", quarterly: "분기", semiannual: "반기"};
function StatementTable({rows}: {rows: StockStatement[]}) {
  return <div className="semiTableWrap"><table className="semiTable"><thead><tr><th>회계기간 종료일</th><th>구분</th><th>통화</th><th>매출</th><th>영업이익</th><th>순이익</th><th>자료원</th></tr></thead><tbody>
    {[...rows].reverse().map(row => <tr key={`${row.type}:${row.period_end}:${row.currency}`}><td>{row.period_end}</td><td>{labels[row.type]}</td><td>{row.currency}</td><td className="semiNumber">{amount(row.revenue)}</td><td className="semiNumber">{amount(row.operating_income)}</td><td className="semiNumber">{amount(row.net_income)}</td><td>{row.source}</td></tr>)}
  </tbody></table></div>;
}
export function StockInformationPanel({ticker, exchange, refreshKey}: {ticker: string; exchange?: string; refreshKey?: string}) {
  const load = useCallback((signal: AbortSignal, fromSource = false) => getStockInformation(ticker, exchange, signal, fromSource), [ticker, exchange, refreshKey]);
  const {data, error, loading, refreshing, refresh} = usePollingData(load, 300000);
  const groups = data?.financials ?? [];
  return <section className="semiPanel stockInformationPanel">
    <div className="semiPanelHeading semiHeadingSplit"><div><h2>실적 · 투자 지표</h2><p>2025년 1월 1일 이후 회계기간의 확정 실적 · 현재 제공 지표</p></div><button type="button" className="semiTextButton" disabled={refreshing} onClick={refresh}>{refreshing ? "정보 조회 중…" : "정보 다시 조회"}</button></div>
    {error ? <ErrorNotice message={error} /> : null}{loading ? <p>종목 정보를 확인하고 있습니다.</p> : null}
    {data ? <>
      <p className="semiFootnote">시세·지표 조회 {formatDateTime(data.fetched_at)} · 실적 조회 {formatDateTime(data.financials_fetched_at ?? data.fetched_at)}{data.quote?.provider_time ? ` · 시세 기준 봉 시각 ${formatDateTime(data.quote.provider_time)}` : ""}</p>
      {data.company?.sector || data.company?.industry ? <p>{[data.company.sector, data.company.industry].filter(Boolean).join(" / ")}{data.company.number_of_employees ? ` · 임직원 ${data.company.number_of_employees.toLocaleString("ko-KR")}명` : ""}</p> : null}
      {data.quote ? <p>최근 제공 가격 {priceText(data.quote.price)} {data.quote.currency} · 시가총액 {formatMarketCap(data.quote)}</p> : null}
      {data.quote?.provider_date ? <p className="semiFootnote">일봉 제공일 {data.quote.provider_date} · 현재 시세가 제공되지 않아 마지막 확인 가격을 표시합니다.</p> : null}
      <div className="semiTableWrap"><table className="semiTable"><thead><tr><th>PER</th><th>PBR</th><th>EPS ({data.metrics_currency ?? "통화 미확인"})</th><th>배당수익률</th><th>52주 최고 ({data.quote?.currency})</th><th>52주 최저 ({data.quote?.currency})</th></tr></thead><tbody><tr>
        {["per", "pbr", "eps", "dividend_yield", "high_52_week", "low_52_week"].map(key => <td key={key} className="semiNumber">{data.metrics[key] == null ? "—" : `${amount(data.metrics[key])}${key === "dividend_yield" ? "%" : ""}`}</td>)}
      </tr></tbody></table></div>
      {groups.length ? <StatementTable rows={groups} /> : <p className="semiEmpty">2025년 이후 확정 실적이 제공되지 않습니다.</p>}
      {groups.some(row => row.total_assets != null || row.total_debt != null || row.operating_cash_flow != null || row.free_cash_flow != null) ? <details><summary>자산 · 부채 · 현금흐름</summary><div className="semiTableWrap"><table className="semiTable"><thead><tr><th>회계기간 종료일</th><th>구분</th><th>통화</th><th>총자산</th><th>총차입금</th><th>영업현금흐름</th><th>잉여현금흐름</th></tr></thead><tbody>
        {[...groups].reverse().map(row => <tr key={`${row.type}:${row.period_end}:${row.currency}`}><td>{row.period_end}</td><td>{labels[row.type]}</td><td>{row.currency}</td>{["total_assets", "total_debt", "operating_cash_flow", "free_cash_flow"].map(key => <td className="semiNumber" key={key}>{amount(row[key as keyof StockStatement] as number | null | undefined)}</td>)}</tr>)}
      </tbody></table></div></details> : null}
      <p className="semiFootnote">각 행의 통화와 회계기간 기준입니다. 연간·분기·반기 실적은 서로 합산하지 않습니다. {data.financial_coverage?.note ?? "공시되지 않았거나 제공처에 없는 기간은 채우지 않습니다."}</p>
      {data.warnings.map((warning, index) => <p className="semiFootnote" role="status" key={index}>{warning.startsWith("과거 확정 실적 조회 실패:") ? "일부 과거 확정 실적을 제공처에서 가져오지 못했습니다. 확인된 실적만 표시합니다." : warning}</p>)}
      {data.historical_financials_warning ? <p className="semiFootnote" role="status">일부 2025년 과거 실적은 원본에서 확인하지 못했습니다. 확인된 회계기간만 표시합니다.</p> : null}
    </> : null}
  </section>;
}
