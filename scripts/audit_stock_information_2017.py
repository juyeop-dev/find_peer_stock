"""Audit actual 2017 prices and reported financials for every detail listing."""
import audit_stock_information_2024_h2 as audit


if __name__ == "__main__":
    audit.START, audit.END = "2017-01-01", "2017-12-31"
    audit.SCOPE = "2017"
    audit.COVERED_STATUS = "covers_2017"
    audit.PERIODS_KEY = "financial_2017_periods"
    audit.main()
