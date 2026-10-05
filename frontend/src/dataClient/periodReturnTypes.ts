export interface PeriodReturn {
  change_pct: number;
  start_date: string;
  end_date: string;
  basis: "close_to_close";
}

export type PeriodReturns = Record<string, PeriodReturn>;
