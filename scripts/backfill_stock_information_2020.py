"""Recover reported 2020 financials while preserving all later periods."""
import backfill_stock_information_2024_h2 as recovery


def configure():
    recovery.START, recovery.END = "2020-01-01", "2020-12-31"
    recovery.STATE = recovery.info.ROOT / "data/tmp_2020"
    recovery.AUDIT = recovery.info.ROOT / "data/information-audit/2020"
    recovery.TABLE = "financial_2020_updates"
    recovery.COVERAGE_KEY = "historical_2020_coverage"
    recovery.FETCHED_KEY = "historical_2020_fetched_at"
    recovery.RESUME = "python -u scripts/backfill_stock_information_2020.py collect"


if __name__ == "__main__":
    configure()
    recovery.main()
