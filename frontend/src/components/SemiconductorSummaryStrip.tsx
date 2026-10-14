import { formatDateTime } from "../dataClient/formatters";
import type { SemiconductorData } from "../dataClient/semiconductorTypes";

export function SemiconductorSummaryStrip({ data }: { data: SemiconductorData }) {
  return <div className="semiSummaryStrip">
    <div><span>분류 종목</span><strong>{data.stocks.length}개</strong></div>
    <div><span>현재가 수집</span><strong>{data.stocks.filter((stock) => stock.quote.status === "ok").length}개</strong></div>
    <div><span>가격 조회 시각</span><strong>{formatDateTime(data.quoted_at)}</strong></div>
  </div>;
}
