"""Audit actual 2018 prices and reported financials for every detail listing."""
import audit_stock_information_2024_h2 as audit


if __name__ == "__main__":
    audit.START, audit.END = "2018-01-01", "2018-12-31"
    audit.SCOPE = "2018"
    audit.COVERED_STATUS = "covers_2018"
    audit.PERIODS_KEY = "financial_2018_periods"
    audit.main()
