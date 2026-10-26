"""Recover the entire 2024 financial year using an independent resumable state."""
import backfill_stock_information_2024_h2 as recovery


def configure():
    recovery.START = "2024-01-01"
    recovery.STATE = recovery.info.ROOT / "data/tmp_2024"
    recovery.AUDIT = recovery.info.ROOT / "data/information-audit/2024"
    recovery.TABLE = "financial_2024_updates"
    recovery.COVERAGE_KEY = "historical_2024_coverage"
    recovery.FETCHED_KEY = "historical_2024_fetched_at"
    recovery.RESUME = "python -u scripts/backfill_stock_information_2024.py collect"


if __name__ == "__main__":
    configure()
    recovery.main()
