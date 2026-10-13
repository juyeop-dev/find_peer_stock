export interface CreditPoint {
  date: string;
  total: number;
  kospi: number;
  kosdaq: number;
}

export interface CreditData {
  generated_at: string;
  latest_date: string;
  unit: "KRW million";
  metric: string;
  source: string;
  source_url: string;
  history: CreditPoint[];
}
