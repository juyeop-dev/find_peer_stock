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

  return {
    href: `https://finance.yahoo.com/quote/${encodeURIComponent(normalizedTicker)}`,
    label: "Yahoo Finance"
  };
}
