import type { PeriodReturns as PeriodReturnsData } from "../dataClient/periodReturnTypes";
import "./PeriodReturns.css";

const VISIBLE_PERIODS = [{ key: "1w", label: "주간" }, { key: "1m", label: "월간" }] as const;

export function PeriodReturns({ values }: { values?: PeriodReturnsData }) {
  if (!values) return null;
  const available = VISIBLE_PERIODS.filter(({ key }) => values[key]);
  if (!available.length) return null;
  return <div className="periodReturns" aria-label="기간별 상승률">
    {available.map(({ key, label }) => {
      const item = values[key];
      return <span key={key} className={item.change_pct > 0 ? "up" : item.change_pct < 0 ? "down" : "flat"}
        title={`${item.start_date}~${item.end_date} 종가 대비 종가`}>
        {label} {item.change_pct > 0 ? "+" : ""}{item.change_pct.toFixed(2)}%
      </span>;
    })}
  </div>;
}
