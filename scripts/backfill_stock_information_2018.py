"""Recover reported 2018 financials while preserving all later periods."""
import backfill_stock_information_2024_h2 as recovery


def configure():
    recovery.START, recovery.END = "2018-01-01", "2018-12-31"
    recovery.STATE = recovery.info.ROOT / "data/tmp_2018"
    recovery.AUDIT = recovery.info.ROOT / "data/information-audit/2018"
    recovery.TABLE = "financial_2018_updates"
    recovery.COVERAGE_KEY = "historical_2018_coverage"
    recovery.FETCHED_KEY = "historical_2018_fetched_at"
    recovery.RESUME = "python -u scripts/backfill_stock_information_2018.py collect"


if __name__ == "__main__":
    configure()
    recovery.main()
