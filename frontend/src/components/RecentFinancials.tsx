import { formatEok } from "../dataClient/semiconductorMath";
import type { RecentFinancials } from "../dataClient/semiconductorTypes";

function basisLabel(summary?: RecentFinancials): string {
  return summary?.basis === "ttm" ? "TTM · 4개 분기 합계" : summary?.basis === "annual" ? "결산 연간 · 대체" : "자료 부족";
}

export function RecentFinancialCells({ summary }: { summary?: RecentFinancials }) {
  return <>
    <td className="semiNumber semiRecentRevenue">{formatEok(summary?.revenue)}</td>
    <td className={`semiNumber semiRecentOperatingIncome ${(summary?.operating_income ?? 0) < 0 ? "semiDown" : ""}`}>{formatEok(summary?.operating_income)}</td>
    <td className="semiFinancialPeriod"><span>{summary?.period_label ?? "자료 부족"}</span><small>{basisLabel(summary)}</small></td>
  </>;
}

export function RecentFinancialSummary({ summary }: { summary?: RecentFinancials }) {
  return <div className="semiRecentFinancials">
    <div className="semiRecentFinancialHeading"><h3>{summary?.basis === "annual" ? "최근 결산 연간 실적 (대체)" : "최근 1년 실적 (TTM)"}</h3>
      <span className="semiFinancialPeriod">{summary?.period_label ?? "자료 부족"}</span></div>
    <div className="semiRecentFinancialValues">
      <div><span>매출</span><strong>{formatEok(summary?.revenue)}</strong></div>
      <div><span>영업이익</span><strong className={(summary?.operating_income ?? 0) < 0 ? "semiDown" : ""}>{formatEok(summary?.operating_income)}</strong></div>
    </div>
    <p>{summary?.basis === "ttm" ? "TTM은 최신 발표 분기까지 최근 4개 분기의 개별 실적을 합산한 값입니다. 추정치는 제외합니다."
      : summary?.reason ?? "최근 1년 실적을 계산할 발표 자료가 부족합니다."}</p>
    {summary?.basis === "ttm" && summary.reason && <p>{summary.reason}</p>}
  </div>;
}
