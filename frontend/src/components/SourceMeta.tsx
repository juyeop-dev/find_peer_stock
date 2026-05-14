import { formatDateTime } from "../dataClient/formatters";
import type { QuoteSnapshot } from "../dataClient/types";

interface SourceMetaProps {
  generatedAt: string;
  lastAutoCheckedAt?: string | null;
  quote: QuoteSnapshot;
}

export function SourceMeta({ generatedAt, lastAutoCheckedAt, quote }: SourceMetaProps) {
  return (
    <dl className="sourceMeta">
      {lastAutoCheckedAt ? (
        <div>
          <dt>자동 확인</dt>
          <dd>{formatDateTime(lastAutoCheckedAt)}</dd>
        </div>
      ) : null}
      <div>
        <dt>가격 조회</dt>
        <dd>{formatDateTime(quote.fetched_at)}</dd>
      </div>
      <div>
        <dt>JSON 생성</dt>
        <dd>{formatDateTime(generatedAt)}</dd>
      </div>
      <div>
        <dt>출처</dt>
        <dd>{quote.source}</dd>
      </div>
      {quote.market_status ? (
        <div>
          <dt>시장 상태</dt>
          <dd>{quote.market_status === "open" ? "장중" : "장외"}</dd>
        </div>
      ) : null}
      {quote.market_time ? (
        <div>
          <dt>시세 기준</dt>
          <dd>{formatDateTime(quote.market_time)}</dd>
        </div>
      ) : null}
    </dl>
  );
}
