"""Recover reported 2014 financials while preserving all later periods."""
import backfill_stock_information_2024_h2 as recovery


def configure():
    recovery.info.START = "2014-01-01"
    recovery.START, recovery.END = "2014-01-01", "2014-12-31"
    recovery.STATE = recovery.info.ROOT / "data/tmp_2014"
    recovery.AUDIT = recovery.info.ROOT / "data/information-audit/2014"
    recovery.TABLE = "financial_2014_updates"
    recovery.COVERAGE_KEY = "historical_2014_coverage"
    recovery.FETCHED_KEY = "historical_2014_fetched_at"
    recovery.RESUME = "python -u scripts/backfill_stock_information_2014.py collect"


if __name__ == "__main__":
    configure()
    recovery.main()
