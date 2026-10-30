"""Recover reported 2019 financials while preserving all later periods."""
import backfill_stock_information_2024_h2 as recovery


def configure():
    recovery.START, recovery.END = "2019-01-01", "2019-12-31"
    recovery.STATE = recovery.info.ROOT / "data/tmp_2019"
    recovery.AUDIT = recovery.info.ROOT / "data/information-audit/2019"
    recovery.TABLE = "financial_2019_updates"
    recovery.COVERAGE_KEY = "historical_2019_coverage"
    recovery.FETCHED_KEY = "historical_2019_fetched_at"
    recovery.RESUME = "python -u scripts/backfill_stock_information_2019.py collect"


if __name__ == "__main__":
    configure()
    recovery.main()
