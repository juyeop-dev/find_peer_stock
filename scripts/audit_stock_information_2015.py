"""Audit actual 2015 prices and reported financials for every detail listing."""
import audit_stock_information_2024_h2 as audit
from audit_daily_frequency_2015 import main as verify_daily


if __name__ == "__main__":
    verify_daily()
    audit.START, audit.END = "2015-01-01", "2015-12-31"
    audit.SCOPE = "2015"
    audit.COVERED_STATUS = "covers_2015"
    audit.PERIODS_KEY = "financial_2015_periods"
    audit.main()
