import { useEffect, useState } from "react";
import { formatDateTime } from "../dataClient/formatters";

interface DataRefreshStatusProps {
  refreshing: boolean;
  lastCheckedAt?: string | null;
  generatedAt?: string;
  lastSourceAt?: string | null;
  cadence?: "quote" | "daily" | "semiconductor" | "credit" | "sectors";
  onRefresh: () => void;
}

export function DataRefreshStatus({ refreshing, lastCheckedAt, lastSourceAt, generatedAt, cadence = "quote", onRefresh }: DataRefreshStatusProps) {
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 60_000);
    return () => window.clearInterval(timer);
  }, []);
  // The daily archive changes only after a market close, but its published
  // index should still be checked by the same site-wide deployment heartbeat.
  const freshnessTime = lastSourceAt ?? generatedAt;
  const delayed = Boolean(freshnessTime && now - new Date(freshnessTime).getTime() > 20 * 60_000);

  return (
    <>
      <div className="dataRefreshStatus">
        <p>
          <span>{cadence === "credit"
            ? "새로고침하면 금융투자협회 원본에서 최신 발표값을 조회합니다."
            : cadence === "sectors"
            ? "새로고침하면 국내 전체 종목의 업종·수익률·거래대금·시가총액을 원본에서 다시 조회합니다."
            : cadence === "semiconductor"
            ? "새로고침하면 현재가·일봉·투자 지표·실적을 원본 제공처에서 조회합니다."
            : cadence === "daily"
            ? "새로고침하면 최신 목록과 현재가를 원본에서 조회합니다. 과거 기록은 보존됩니다."
            : "새로고침하면 표시된 종목의 현재 값을 원본 제공처에서 직접 조회합니다."}</span>
          {lastSourceAt ? <span className="sourceFetchedAt">원본 조회 완료 · {formatDateTime(lastSourceAt)}</span> : null}
          {lastCheckedAt ? <span>브라우저 확인 · {formatDateTime(lastCheckedAt)}</span> : null}
        </p>
        <button type="button" className="refreshButton" disabled={refreshing} onClick={onRefresh}>
          {refreshing ? "조회 중…" : "새로고침"}
        </button>
      </div>
      {delayed ? <p className="dataAgeNotice" role="status">
        데이터 생성 후 20분 이상 지났습니다. 자동 업데이트가 지연될 수 있어요.
        {" "}{lastSourceAt ? "마지막 원본 조회" : "마지막 생성"} · {formatDateTime(freshnessTime!)}
      </p> : null}
    </>
  );
}
