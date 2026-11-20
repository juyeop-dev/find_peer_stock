"""Audit actual 2020 prices and reported financials for every detail listing."""
import audit_stock_information_2024_h2 as audit


if __name__ == "__main__":
    audit.main(audit.financial_request(year=2020, root=audit.information.ROOT))
