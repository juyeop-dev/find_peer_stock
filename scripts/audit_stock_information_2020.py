"""Audit actual 2020 prices and reported financials for every detail listing."""
import audit_stock_information_2024_h2 as audit


if __name__ == "__main__":
    audit.START, audit.END = "2020-01-01", "2020-12-31"
    audit.SCOPE = "2020"
    audit.COVERED_STATUS = "covers_2020"
    audit.PERIODS_KEY = "financial_2020_periods"
    audit.main()
