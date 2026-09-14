export type HighType = "52_week" | "all_time";

export interface NewHighCounts {
  total: number;
  high_52_week: number;
  high_all_time: number;
}

export interface NewHighMarket {
  id: string;
  label: string;
  timezone: string;
  refresh_after?: string;
  default_exchange: string;
  exchanges: { id: string; label: string }[];
}

export interface NewHighReportIndex {
  market: string;
  date: string;
  counts: NewHighCounts;
  exchanges: Record<string, NewHighCounts>;
}

export interface NewHighIndex {
  schema_version: 1;
  markets: NewHighMarket[];
  reports: NewHighReportIndex[];
  refresh?: Record<string, NewHighRefresh>;
}

export interface NewHighRefresh {
  status: "updated" | "pending" | "error" | "closed" | "unsupported";
  target_date?: string;
  last_attempt_at?: string;
  last_success_at?: string;
  last_success_date?: string;
  next_retry_at?: string;
  message?: string;
}

export interface NewHighEntry {
  ticker: string;
  name: string;
  exchange: string;
  category: string;
  high_type: HighType;
  reason: string;
  description?: string;
  change_pct?: number | null;
}

export interface NewHighReport {
  schema_version: 1;
  market: string;
  date: string;
  summary?: string;
  category_reasons?: Record<string, string>;
  sources?: { label: string; url?: string }[];
  entries: NewHighEntry[];
}
