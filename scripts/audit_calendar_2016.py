"""Validate every 2016 calendar session and domestic historical series."""
from audit_calendar_2023 import main
import json
from stock_chart_history import ROOT


if __name__ == "__main__":
    proof = ROOT / "data/information-audit/2016/japan-gap-recovery.json"
    prices = ROOT / "data/information-audit/2016/japan-price-recovery.json"
    assert proof.exists() and prices.exists(), "Complete the verified 2016-07-11 Japan recovery before final publication"
    assert json.loads(proof.read_bytes())["metadata"]["session_symbols"] > 1500
    main(year=2016)
