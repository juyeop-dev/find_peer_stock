import { formatPercent, formatWon } from "../dataClient/semiconductorMath";

export function PriceWithChange({price, change}: {price: number; change: number | null}) {
  const tone = change == null || change === 0 ? "" : change > 0 ? "semiUp" : "semiDown";
  return <span className="priceWithChange">
    <span className="stockPriceValue">{formatWon(price)}</span>
    <span className={`priceDayChange ${tone}`} aria-label={`당일 등락률 ${change == null ? "미제공" : formatPercent(change)}`}>
      <span className="priceDayLabel">당일</span>{change == null ? "—" : formatPercent(change)}
    </span>
  </span>;
}
