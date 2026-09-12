import { formatDateTime } from "../dataClient/formatters";
import type { QuoteSnapshot } from "../dataClient/types";

interface SourceMetaProps {
  generatedAt: string;
  quote: QuoteSnapshot;
}

export function SourceMeta({ generatedAt, quote }: SourceMetaProps) {
  const hasSuccessfulQuote = quote.price !== null && quote.status !== "error";
  const notFetched = !hasSuccessfulQuote && quote.refresh_status === "not_fetched";
  return (
    <dl className="sourceMeta">
      <div>
        <dt>{hasSuccessfulQuote ? "가격 조회 성공" : notFetched ? "가격 조회" : "가격 조회 시도"}</dt>
        <dd>{notFetched ? "미조회" : formatDateTime(quote.fetched_at)}</dd>
      </div>
      <div>
        <dt>데이터 생성</dt>
        <dd>{formatDateTime(generatedAt)}</dd>
      </div>
      {quote.last_checked_at && quote.last_checked_at !== quote.fetched_at ? (
        <div>
          <dt>가격 조회 시도</dt>
          <dd>{formatDateTime(quote.last_checked_at)}</dd>
        </div>
      ) : null}
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
