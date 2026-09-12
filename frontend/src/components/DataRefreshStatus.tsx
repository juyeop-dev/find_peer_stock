import { useEffect, useState } from "react";
import { formatDateTime } from "../dataClient/formatters";

interface DataRefreshStatusProps {
  refreshing: boolean;
  lastCheckedAt?: string | null;
  generatedAt?: string;
  onRefresh: () => void;
}

export function DataRefreshStatus({ refreshing, lastCheckedAt, generatedAt, onRefresh }: DataRefreshStatusProps) {
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 60_000);
    return () => window.clearInterval(timer);
  }, []);
  const delayed = Boolean(generatedAt && now - new Date(generatedAt).getTime() > 20 * 60_000);

  return (
    <>
      <div className="dataRefreshStatus">
        <p>
          <span>{generatedAt
            ? "시세 업데이트 목표는 5분 간격이며, 화면은 1분마다 확인합니다."
            : "게시된 데이터를 1분마다 자동 확인합니다."}</span>
          {lastCheckedAt ? <span>브라우저 확인 · {formatDateTime(lastCheckedAt)}</span> : null}
        </p>
        <button type="button" className="refreshButton" disabled={refreshing} onClick={onRefresh}>
          {refreshing ? "확인 중…" : "새로고침"}
        </button>
      </div>
      {delayed ? <p className="dataAgeNotice" role="status">
        데이터 생성 후 20분 이상 지났습니다. 자동 업데이트가 지연될 수 있어요.
        {" "}마지막 생성 · {formatDateTime(generatedAt!)}
      </p> : null}
    </>
  );
}
