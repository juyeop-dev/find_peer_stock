"""Recover reported 2016 financials while preserving all later periods."""
import backfill_stock_information_2024_h2 as recovery


def configure():
    recovery.info.START = "2016-01-01"
    recovery.START, recovery.END = "2016-01-01", "2016-12-31"
    recovery.STATE = recovery.info.ROOT / "data/tmp_2016"
    recovery.AUDIT = recovery.info.ROOT / "data/information-audit/2016"
    recovery.TABLE = "financial_2016_updates"
    recovery.COVERAGE_KEY = "historical_2016_coverage"
    recovery.FETCHED_KEY = "historical_2016_fetched_at"
    recovery.RESUME = "python -u scripts/backfill_stock_information_2016.py collect"


if __name__ == "__main__":
    configure()
    recovery.main()
