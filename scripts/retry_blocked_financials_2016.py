"""Requery a frozen disjoint roster of initial sandbox-denied lookups."""
import json
from dataclasses import replace
import sys

import backfill_stock_information_2016 as year
import backfill_stock_information_2024_h2 as recovery
import stock_chart_history as charts


if __name__ == "__main__":
    request = year.configure()
    rows = json.loads((charts.ROOT / "data/tmp_2016/blocked-retry-roster.json").read_bytes())
    request = replace(request, audit=request.audit / "blocked-network-retry")
    sys.argv = [sys.argv[0], "collect", "--workers", "6"]
    recovery.main(request=request, rows=rows)
