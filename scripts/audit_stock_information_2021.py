"""Audit actual 2021 prices and reported financials for every detail listing."""
import audit_stock_information_2024_h2 as audit


if __name__ == "__main__":
    audit.START, audit.END = "2021-01-01", "2021-12-31"
    audit.SCOPE = "2021"
    audit.COVERED_STATUS = "covers_2021"
    audit.PERIODS_KEY = "financial_2021_periods"
    audit.main()
