import type { NewHighMarket, NewHighRefresh } from "./newHighTypes";

export interface TurnoverReportIndex {
  market: string;
  date: string;
  count: number;
  total_turnover: number;
  currency: string | null;
}

export interface TurnoverIndex {
  schema_version: 1;
  markets: NewHighMarket[];
  reports: TurnoverReportIndex[];
  refresh?: Record<string, NewHighRefresh>;
}

export interface TurnoverEntry {
  rank: number;
  ticker: string;
  name: string;
  exchange: string;
  price: number;
  change_pct: number | null;
  turnover: number;
  currency: string;
  market_cap: number | null;
  sector: string;
  industry: string;
  logo_url?: string;
  source_symbol?: string;
}

export interface TurnoverReport {
  schema_version: 1;
  market: string;
  date: string;
  summary?: string;
  sources?: { label: string; url?: string }[];
  entries: TurnoverEntry[];
}
