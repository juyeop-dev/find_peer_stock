"""Audit actual 2019 prices and reported financials for every detail listing."""
import audit_stock_information_2024_h2 as audit


if __name__ == "__main__":
    audit.START, audit.END = "2019-01-01", "2019-12-31"
    audit.SCOPE = "2019"
    audit.COVERED_STATUS = "covers_2019"
    audit.PERIODS_KEY = "financial_2019_periods"
    audit.main()
