"""Validate complete-year financial and price packs with independent coverage."""
import audit_stock_information_2024_h2 as audit


if __name__ == "__main__":
    audit.main(audit.financial_request(year=2024, root=audit.information.ROOT))
