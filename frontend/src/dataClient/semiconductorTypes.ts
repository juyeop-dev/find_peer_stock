export interface SemiconductorPrice {
  date: string;
  close: number;
  adjusted_close: number;
  volume: number | null;
}

export interface SemiconductorFinancial {
  period: string;
  type: "annual" | "quarterly";
  revenue: number | null;
  operating_income: number | null;
  net_income: number | null;
}

export interface SemiconductorQuote {
  price: number | null;
  change: number | null;
  change_pct: number | null;
  provider_time: string | null;
  market_status: string | null;
  status: "ok" | "stale";
  fetched_at: string;
  source: string;
  error?: string;
}

export interface SemiconductorStock {
  ticker: string;
  code: string;
  name: string;
  market: "KOSPI" | "KOSDAQ";
  major: string;
  middle: string;
  minor: string;
  history: SemiconductorPrice[];
  annual_financials: SemiconductorFinancial[];
  quarterly_financials: SemiconductorFinancial[];
  metrics: Record<string, string | null>;
  quote: SemiconductorQuote;
  data_errors: string[];
}

export interface SemiconductorData {
  generated_at: string;
  quoted_at: string;
  history_source: string;
  financial_source: string;
  financial_unit: string;
  coverage: "curated";
  stocks: SemiconductorStock[];
}
