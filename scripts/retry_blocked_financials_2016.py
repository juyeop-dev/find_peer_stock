"""Requery a frozen disjoint roster of initial sandbox-denied lookups."""
import json
import sys

import backfill_stock_information_2016 as year
import backfill_stock_information_2024_h2 as recovery
import stock_chart_history as charts


if __name__ == "__main__":
    year.configure()
    rows = json.loads((charts.ROOT / "data/tmp_2016/blocked-retry-roster.json").read_bytes())
    charts.roster = lambda: rows
    recovery.AUDIT = recovery.AUDIT / "blocked-network-retry"
    sys.argv = [sys.argv[0], "collect", "--workers", "6"]
    recovery.main()
