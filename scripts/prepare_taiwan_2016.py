"""Cache verified same-listing charts before official Saturday recovery."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json

from backfill_yahoo_calendars import scan_universe
from backfill_european_new_highs import cached_chart
from stock_chart_history import ROOT, write_json


def main():
    target = ROOT / "data/tmp_2016/taiwan-gap-universe.json"
    if target.exists():
        universe = json.loads(target.read_bytes())
    else:
        universe = {"rows": scan_universe("taiwan", timeout=30), "fetched_at": datetime.now(timezone.utc).isoformat()}
        write_json(target, universe)
    errors = {}
    def fetch(row):
        return cached_chart(row, "1D", 3200, cache_dir=ROOT / "data/tmp_tradingview_chart", timeout=20)
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(fetch, row): row for row in universe["rows"]}
        for count, future in enumerate(as_completed(futures), 1):
            row = futures[future]
            try:
                future.result()
            except Exception as error:
                if any(term in str(error).lower() for term in ["rate limit", "forbidden", "unauthorized", "permission"]):
                    raise
                errors[row["symbol"]] = f"{type(error).__name__}: {error}"
            if count % 100 == 0:
                print(f"Taiwan verified chart bases {count}/{len(futures)}; unavailable={len(errors)}", flush=True)
    write_json(ROOT / "data/information-audit/2016/taiwan-chart-bases.json", {"total": len(futures), "unavailable": errors})


if __name__ == "__main__":
    main()
