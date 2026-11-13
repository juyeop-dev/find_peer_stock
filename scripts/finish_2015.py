"""Publish and build only after the 2015 source and preservation audits pass."""
import json
import os
import time

from finalize_2015 import ROOT, STATE, PY, run


def main():
    while True:
        try:
            stages = {path.stem: json.loads(path.read_bytes()) for path in STATE.glob("stage-*.json")}
        except (FileNotFoundError, ValueError):
            time.sleep(.2)
            continue
        verified=stages.get("stage-verified-provider-recovery",{})
        if verified.get("status")=="failed":
            raise RuntimeError("Resolve verified provider recovery before publication")
        calendars=stages.get("stage-publication-calendars",{})
        if calendars.get("status")=="failed":
            raise RuntimeError("Resolve calendar publication before building")
        if verified.get("status")=="complete" and calendars.get("status")=="complete":
            break
        time.sleep(2)
    run("publication-details", [[*PY, "scripts/publish_2015.py", "--phase", "details"]])
    run("public-audit", [[*PY, "scripts/audit_publication_2015.py"],
                         [*PY, "scripts/audit_calendar_prices_2015.py"],
                         [*PY, "scripts/audit_preservation_2015.py"]])
    os.environ["VITE_BASE_PATH"] = "/find_peer_stock/"
    os.environ.pop("VITE_LIVE_API_URL", None)
    run("build", [["node", "frontend/node_modules/vite/bin/vite.js", "build", "frontend", "--outDir", str(STATE / "site")]])
    run("artifact-audit", [[*PY, "scripts/audit_publication_2015.py", "--artifact", str(STATE / "site")]])
    print("2015 public data and production-path static artifact verified", flush=True)


if __name__ == "__main__":
    main()
