"""Audit actual 2022 prices and reported financials for every detail listing."""
import audit_stock_information_2024_h2 as audit


if __name__ == "__main__":
    audit.START, audit.END = "2022-01-01", "2022-12-31"
    audit.SCOPE = "2022"
    audit.COVERED_STATUS = "covers_2022"
    audit.PERIODS_KEY = "financial_2022_periods"
    audit.main()
