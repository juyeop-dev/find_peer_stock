"""Recover reported 2021 financials while preserving all later periods."""
import backfill_stock_information_2024_h2 as recovery


def configure():
    recovery.START, recovery.END = "2021-01-01", "2021-12-31"
    recovery.STATE = recovery.info.ROOT / "data/tmp_2021"
    recovery.AUDIT = recovery.info.ROOT / "data/information-audit/2021"
    recovery.TABLE = "financial_2021_updates"
    recovery.COVERAGE_KEY = "historical_2021_coverage"
    recovery.FETCHED_KEY = "historical_2021_fetched_at"
    recovery.RESUME = "python -u scripts/backfill_stock_information_2021.py collect"


if __name__ == "__main__":
    configure()
    recovery.main()
