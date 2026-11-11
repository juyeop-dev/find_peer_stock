"""Recover reported 2017 financials while preserving all later periods."""
import backfill_stock_information_2024_h2 as recovery


def configure():
    recovery.info.START = "2017-01-01"
    recovery.START, recovery.END = "2017-01-01", "2017-12-31"
    recovery.STATE = recovery.info.ROOT / "data/tmp_2017"
    recovery.AUDIT = recovery.info.ROOT / "data/information-audit/2017"
    recovery.TABLE = "financial_2017_updates"
    recovery.COVERAGE_KEY = "historical_2017_coverage"
    recovery.FETCHED_KEY = "historical_2017_fetched_at"
    recovery.RESUME = "python -u scripts/backfill_stock_information_2017.py collect"


if __name__ == "__main__":
    configure()
    recovery.main()
