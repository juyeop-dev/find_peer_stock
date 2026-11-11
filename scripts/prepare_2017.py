"""Prepare resumable 2017 collectors and preserve the current workspace sources."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil

ROOT = Path(__file__).resolve().parents[1]


def main():
    baseline = ROOT / "data/tmp_2017/baseline"
    baseline.mkdir(parents=True, exist_ok=True)
    manifest = baseline / "manifest.json"
    if not manifest.exists():
        hashes = {}
        for namespace in ["new-highs/reports", "turnover/reports", "sectors/daily", "rebounds/reports"]:
            for path in (ROOT / "data" / namespace).rglob("*"):
                if path.is_file():
                    hashes[path.relative_to(ROOT).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
        for namespace in ["stock-information", "stock-history", "semiconductor", "investors", "credit", "generated/stocks"]:
            shutil.copytree(ROOT / "data" / namespace, baseline / namespace, dirs_exist_ok=True)
        manifest.write_text(json.dumps({"created_at": datetime.now(timezone.utc).isoformat(),
            "original_daily_sha256": hashes}, indent=2), encoding="utf-8")
        print(f"Preserved baseline and {len(hashes)} original daily source hashes", flush=True)
    names = ["backfill_stock_information", "extend_stock_history", "backfill_credit",
             "backfill_sector_history", "backfill_semiconductor_history", "backfill_sec_financials",
             "audit_calendar", "audit_stock_information", "audit_preservation", "finalize_financials",
             "finalize_korea", "fetch_korea_source", "complete_history_audit"]
    for name in names:
        target = ROOT / f"scripts/{name}_2017.py"
        if target.exists():
            continue
        source = (ROOT / f"scripts/{name}_2018.py").read_text(encoding="utf-8")
        source = re.sub(r"(?<!\d)(?:2017|2018|2019)(?!\d)", lambda match: str(int(match[0]) - 1), source)
        source = source.replace("_2018", "_2017").replace("2026-11-02-2017", "2026-11-11-2017")
        # Semiconductor membership has grown since the 2018 expansion.
        if name == "audit_preservation":
            source = source.replace("len(old['stocks']) == len(new['stocks']) == 102", "len(old['stocks']) == len(new['stocks'])")
            source = source.replace("result['preserved_semiconductor_listings'] = 102", "result['preserved_semiconductor_listings'] = len(old['stocks'])")
        target.write_text(source, encoding="utf-8")
    target = ROOT / "scripts/backfill_investors_2017.mjs"
    if not target.exists():
        target.write_text((ROOT / "scripts/backfill_investors_2018.mjs").read_text(encoding="utf-8").replace("2018", "2017"), encoding="utf-8")
    print("Prepared 2017 collectors", flush=True)


if __name__ == "__main__":
    main()
