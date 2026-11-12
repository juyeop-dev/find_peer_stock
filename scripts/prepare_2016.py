"""Prepare the 2016 expansion without overwriting existing work or evidence."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil

ROOT = Path(__file__).resolve().parents[1]
NAMES = [
    "backfill_stock_information", "backfill_sec_financials", "backfill_credit",
    "backfill_sector_history", "backfill_semiconductor_history", "backfill_chart_replay",
    "extend_stock_history", "complete_history_audit", "finalize_financials",
    "finalize_korea", "fetch_korea_source", "audit_calendar", "audit_stock_information",
    "audit_preservation", "checkpoint", "publish", "status", "run",
    "exclude_closed_price_observations", "prune_closed_sessions",
]


def main():
    baseline = ROOT / "data/tmp_2016/baseline"
    baseline.mkdir(parents=True, exist_ok=True)
    manifest = baseline / "manifest.json"
    if not manifest.exists():
        hashes = {}
        for namespace in ["new-highs/reports", "turnover/reports", "sectors/daily", "rebounds/reports"]:
            for path in (ROOT / "data" / namespace).rglob("*"):
                if path.is_file():
                    hashes[path.relative_to(ROOT).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
        for namespace in ["stock-information", "stock-history", "semiconductor", "investors", "credit", "generated/stocks", "chart-replay"]:
            shutil.copytree(ROOT / "data" / namespace, baseline / namespace, dirs_exist_ok=True)
        manifest.write_text(json.dumps({"created_at": datetime.now(timezone.utc).isoformat(),
            "original_daily_sha256": hashes}, indent=2), encoding="utf-8")
        print(f"Preserved baseline and {len(hashes)} original daily source hashes", flush=True)
    for name in NAMES:
        target = ROOT / f"scripts/{name}_2016.py"
        if target.exists():
            continue
        source = (ROOT / f"scripts/{name}_2017.py").read_text(encoding="utf-8")
        source = re.sub(r"201[678]", lambda match: str(int(match[0]) - 1), source)
        source = source.replace("2026-11-11-2016", "2026-11-12-2016")
        target.write_text(source, encoding="utf-8")
    target = ROOT / "scripts/backfill_investors_2016.mjs"
    if not target.exists():
        target.write_text((ROOT / "scripts/backfill_investors_2017.mjs").read_text(encoding="utf-8").replace("2017", "2016"), encoding="utf-8")
    print("Prepared 2016 collectors", flush=True)


if __name__ == "__main__":
    main()
