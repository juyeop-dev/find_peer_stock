"""Audit actual 2023 price and financial coverage for every detail listing."""
import audit_stock_information_2024_h2 as audit


if __name__ == "__main__":
    audit.START, audit.END = "2023-01-01", "2023-12-31"
    audit.SCOPE = "2023"
    audit.COVERED_STATUS = "covers_2023"
    audit.PERIODS_KEY = "financial_2023_periods"
    audit.main()
