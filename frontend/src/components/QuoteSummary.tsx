import { changeTone, formatChange, formatPrice, quoteRefreshNotice } from "../dataClient/formatters";
import type { QuoteSnapshot } from "../dataClient/types";
import { SourceMeta } from "./SourceMeta";

interface QuoteSummaryProps {
  quote: QuoteSnapshot;
  generatedAt: string;
}

export function QuoteSummary({ quote, generatedAt }: QuoteSummaryProps) {
  const tone = changeTone(quote);
  const refreshNotice = quoteRefreshNotice(quote);

  return (
    <section className="quoteSummary" aria-label="가격 요약">
      <div>
        <span className="eyebrow">현재 가격</span>
        <div className="priceLine">{formatPrice(quote)}</div>
        <div className={`changeLine ${tone}`}>{formatChange(quote)}</div>
      </div>
      <SourceMeta generatedAt={generatedAt} quote={quote} />
      {refreshNotice ? <p className="quoteError" role="status">{refreshNotice}</p> : null}
    </section>
  );
}
