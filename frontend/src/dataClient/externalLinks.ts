const MSN_STOCK_DETAIL_URLS: Record<string, string> = {
  "6503.T": "https://www.msn.com/ko-kr/money/stockdetails/6503-jp-stock/fi-a9fmtc?ocid=edgsp&id=a9fmtc"
};

export interface ExternalQuoteLink {
  href: string;
  label: string;
}

export function getExternalQuoteLink(ticker: string): ExternalQuoteLink {
  const normalizedTicker = ticker.trim().toUpperCase();
  const msnUrl = MSN_STOCK_DETAIL_URLS[normalizedTicker];

  if (msnUrl) {
    return {
      href: msnUrl,
      label: "MSN Money"
    };
  }

  if (/^(EURONEXT|XETR|LSE|SIX):[A-Z0-9.\-]+$/.test(normalizedTicker)) {
    return {
      href: `https://www.tradingview.com/symbols/${normalizedTicker.replace(":", "-")}/`,
      label: "TradingView"
    };
  }

  return {
    href: `https://finance.yahoo.com/quote/${encodeURIComponent(normalizedTicker)}`,
    label: "Yahoo Finance"
  };
}
