"""Recover reported 2022 financials while preserving all later periods."""
import backfill_stock_information_2024_h2 as recovery


def configure():
    recovery.START, recovery.END = "2022-01-01", "2022-12-31"
    recovery.STATE = recovery.info.ROOT / "data/tmp_2022"
    recovery.AUDIT = recovery.info.ROOT / "data/information-audit/2022"
    recovery.TABLE = "financial_2022_updates"
    recovery.COVERAGE_KEY = "historical_2022_coverage"
    recovery.FETCHED_KEY = "historical_2022_fetched_at"
    recovery.RESUME = "python -u scripts/backfill_stock_information_2022.py collect"


if __name__ == "__main__":
    configure()
    recovery.main()
