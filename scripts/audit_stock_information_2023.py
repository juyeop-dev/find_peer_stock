"""Audit actual 2023 price and financial coverage for every detail listing."""
import audit_stock_information_2024_h2 as audit


if __name__ == "__main__":
    audit.main(audit.financial_request(year=2023, root=audit.information.ROOT))
