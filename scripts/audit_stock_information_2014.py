"""Audit actual 2014 prices and reported financials for every detail listing."""
import audit_stock_information_2024_h2 as audit
from audit_daily_frequency_2014 import main as verify_daily


if __name__ == "__main__":
    verify_daily()
    audit.START, audit.END = "2014-01-01", "2014-12-31"
    audit.SCOPE = "2014"
    audit.COVERED_STATUS = "covers_2014"
    audit.PERIODS_KEY = "financial_2014_periods"
    audit.main()
