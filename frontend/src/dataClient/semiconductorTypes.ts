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

export interface RecentFinancials {
  basis: "ttm" | "annual" | "unavailable";
  period_label: string;
  periods: string[];
  latest_reported_period: string | null;
  revenue: number | null;
  operating_income: number | null;
  reason: string | null;
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

export interface SemiconductorClassification {
  major: string;
  middle: string;
  minor: string;
}

export interface SemiconductorStock {
  ticker: string;
  code: string;
  name: string;
  business_summary?: string;
  business_sources?: { label: string; url: string }[];
  market: "KOSPI" | "KOSDAQ";
  major: string;
  middle: string;
  minor: string;
  classifications?: SemiconductorClassification[];
  history: SemiconductorPrice[];
  annual_financials: SemiconductorFinancial[];
  quarterly_financials: SemiconductorFinancial[];
  recent_financials?: RecentFinancials;
  metrics: Record<string, string | null>;
  quote: SemiconductorQuote;
  data_errors: string[];
}

export function stockClassifications(stock: SemiconductorStock): SemiconductorClassification[] {
  return stock.classifications?.length ? stock.classifications : [stock];
}

export interface SemiconductorData {
  generated_at: string;
  financials_updated_at?: string;
  quoted_at: string;
  history_source: string;
  financial_source: string;
  financial_unit: string;
  coverage: "curated";
  categories?: SemiconductorClassification[];
  stocks: SemiconductorStock[];
}
