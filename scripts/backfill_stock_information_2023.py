"""Recover reported 2023 financials without replacing later published periods."""
import backfill_stock_information_2024_h2 as recovery


def configure():
    recovery.START = "2023-01-01"
    recovery.END = "2023-12-31"
    recovery.STATE = recovery.info.ROOT / "data/tmp_2023"
    recovery.AUDIT = recovery.info.ROOT / "data/information-audit/2023"
    recovery.TABLE = "financial_2023_updates"
    recovery.COVERAGE_KEY = "historical_2023_coverage"
    recovery.FETCHED_KEY = "historical_2023_fetched_at"
    recovery.RESUME = "python -u scripts/backfill_stock_information_2023.py collect"


if __name__ == "__main__":
    configure()
    recovery.main()
