import { changeTone, formatChange, formatPrice } from "../dataClient/formatters";
import type { QuoteSnapshot } from "../dataClient/types";
import { SourceMeta } from "./SourceMeta";

interface QuoteSummaryProps {
  quote: QuoteSnapshot;
  generatedAt: string;
  lastAutoCheckedAt?: string | null;
}

export function QuoteSummary({ quote, generatedAt, lastAutoCheckedAt }: QuoteSummaryProps) {
  const tone = changeTone(quote);

  return (
    <section className="quoteSummary" aria-label="가격 요약">
      <div>
        <span className="eyebrow">현재 가격</span>
        <div className="priceLine">{formatPrice(quote)}</div>
        <div className={`changeLine ${tone}`}>{formatChange(quote)}</div>
      </div>
      <SourceMeta generatedAt={generatedAt} lastAutoCheckedAt={lastAutoCheckedAt} quote={quote} />
      {quote.status === "error" ? <p className="quoteError">{quote.error}</p> : null}
    </section>
  );
}
