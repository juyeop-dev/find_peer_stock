"""Apply independently repaired sessions after collectors stop writing the packs."""
import json
from pathlib import Path
import time

from finalize_2015 import ROOT, STATE, PY, run


def wait_stage(name, allow_failed=False):
    while True:
        path=STATE / f"stage-{name}.json"
        if path.exists():
            value=json.loads(path.read_bytes())
            if value["status"]=="failed" and not allow_failed:
                raise RuntimeError(f"Resolve {name} before final source verification")
            if value["status"]=="complete" or allow_failed and value["status"]=="failed":
                return
        time.sleep(2)


def main():
    wait_stage("histories")
    wait_stage("financial-finalize")
    wait_stage("audits", allow_failed=True)
    for market,day in [("japan","2015-12-25"),("china","2015-02-25")]:
        while True:
            proof=ROOT / f"data/information-audit/2015/{market}-gap-recovery.json"
            adjacent=ROOT / f"data/information-audit/2015/{market}-adjacent-source.json"
            try:
                if proof.exists() and adjacent.exists() and json.loads(proof.read_bytes())["date"]==day:
                    break
            except ValueError:
                pass
            time.sleep(2)
    run("verified-provider-recovery", [
        [*PY,"scripts/import_japan_recovered_2015.py","--no-export"],
        [*PY,"scripts/import_china_recovered_2015.py","--no-export"],
        [*PY,"scripts/complete_history_audit_2015.py","--no-export"],
        [*PY,"scripts/exclude_closed_price_observations_2015.py"],
        [*PY,"scripts/finalize_financials_2015.py"],
        [*PY,"scripts/checkpoint_2015.py"],
        [*PY,"scripts/audit_calendar_2015.py"],
        [*PY,"scripts/audit_stock_information_2015.py"],
        [*PY,"scripts/audit_preservation_2015.py"],
        [*PY,"scripts/audit_japan_quality_2015.py"],
        [*PY,"scripts/audit_china_quality_2015.py"],
        [*PY,"scripts/audit_calendar_sources_2015.py"],
    ])
    print("Independent provider recovery, reported financials and preservation verified",flush=True)


if __name__=="__main__":
    main()
