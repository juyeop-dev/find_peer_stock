"""Audit actual 2014 prices and reported financials for every detail listing."""
import audit_stock_information_2024_h2 as audit
from audit_daily_frequency_2014 import main as verify_daily


if __name__ == "__main__":
    verify_daily()
    audit.main(audit.financial_request(year=2014, root=audit.information.ROOT))
