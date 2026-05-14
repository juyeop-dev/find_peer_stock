export interface SiteIndex {
  generated_at: string;
  stocks: StockIndexItem[];
  featured_tickers: string[];
  market_indices: MarketIndexItem[];
}

export interface MarketIndexItem {
  name: string;
  ticker?: string;
  price?: number | null;
  change_pct?: number | null;
  status?: string;
}

export interface StockIndexItem {
  id: string;
  ticker: string;
  name_kr: string;
  name_en: string;
  country: string;
  theme: string;
  is_target: boolean;
  summary_path: string;
}

export interface CompanyProfile {
  id: string;
  name_kr: string;
  name_en: string;
  ticker: string;
  country: string;
  theme: string;
  market_note: string;
  sector: string;
  note: string;
  title: string;
  is_target: boolean;
}

export interface QuoteSnapshot {
  ticker: string;
  price: number | null;
  previous_close: number | null;
  change: number | null;
  change_pct: number | null;
  currency: string;
  source: string;
  fetched_at: string;
  market_time: string | null;
  basis_label: string | null;
  status: "ok" | "error";
  error: string | null;
  market?: string;
  market_country?: string;
  market_timezone?: string;
  market_status?: "open" | "closed";
  market_status_reason?: string;
  market_session?: string;
  refresh_status?: string;
  last_checked_at?: string;
}

export interface PeerGroup {
  group: {
    emoji?: string | null;
    name: string;
    summary?: string | null;
  };
  peers: PeerCompany[];
}

export interface PeerCompany {
  company: CompanyProfile;
  quote: QuoteSnapshot;
  summary_path: string;
}

export interface StockSummary {
  generated_at: string;
  company: CompanyProfile;
  quote: QuoteSnapshot;
  peer_groups: PeerGroup[];
  sources: string[];
}
