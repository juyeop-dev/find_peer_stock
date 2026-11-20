"""Audit actual 2016 prices and reported financials for every detail listing."""
import audit_stock_information_2024_h2 as audit
import json
from stock_chart_history import ROOT


if __name__ == "__main__":
    proof = ROOT / "data/information-audit/2016/daily-frequency-recovery.json"
    assert proof.exists() and not json.loads(proof.read_bytes())["remaining_monthly"], "Daily frequency repair must finish before coverage is published"
    audit.main(audit.financial_request(year=2016, root=audit.information.ROOT))
