"""Validate complete-year financial and price packs with independent coverage."""
import audit_stock_information_2024_h2 as audit


if __name__ == "__main__":
    audit.START = "2024-01-01"
    audit.SCOPE = "2024"
    audit.COVERED_STATUS = "covers_2024"
    audit.PERIODS_KEY = "financial_2024_periods"
    audit.main()
