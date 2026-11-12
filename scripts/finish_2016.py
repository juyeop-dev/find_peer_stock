"""Publish and build only after the 2016 source and preservation audits pass."""
import json
import os
import time

from finalize_2016 import ROOT, STATE, PY, run


def main():
    while True:
        try:
            stages = {path.stem: json.loads(path.read_bytes()) for path in STATE.glob("stage-*.json")}
        except (FileNotFoundError, ValueError):
            time.sleep(.2)
            continue
        source_stages = {"stage-audits", "stage-histories", "stage-japan-quality", "stage-daily-frequency-finalize",
                         "stage-financial-finalize", "stage-financial-complete", "stage-korea-finalize",
                         "stage-europe-turnover", "stage-taiwan-gap"}
        failed = [name for name, value in stages.items() if name in source_stages and value["status"] == "failed"]
        if failed:
            raise RuntimeError("Resolve failed stages before publication: " + ", ".join(failed))
        if stages.get("stage-audits", {}).get("status") == "complete" and stages.get("stage-daily-frequency-finalize", {}).get("status") == "complete":
            break
        time.sleep(2)
    run("publication-details", [[*PY, "scripts/publish_2016.py", "--phase", "details"]])
    run("public-audit", [[*PY, "scripts/audit_publication_2016.py"],
                         [*PY, "scripts/audit_calendar_prices_2016.py"],
                         [*PY, "scripts/audit_preservation_2016.py"]])
    os.environ["VITE_BASE_PATH"] = "/find_peer_stock/"
    os.environ.pop("VITE_LIVE_API_URL", None)
    run("build", [["node", "frontend/node_modules/vite/bin/vite.js", "build", "frontend", "--outDir", str(STATE / "site")]])
    run("artifact-audit", [[*PY, "scripts/audit_publication_2016.py", "--artifact", str(STATE / "site")]])
    print("2016 public data and production-path static artifact verified", flush=True)


if __name__ == "__main__":
    main()
