"""Preserve the existing dataset and prepare independently resumable 2015 jobs."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
NAMES = [
    "backfill_stock_information", "backfill_sec_financials", "backfill_credit",
    "backfill_sector_history", "backfill_semiconductor_history", "backfill_chart_replay",
    "extend_stock_history", "complete_history_audit", "finalize_financials",
    "finalize_korea", "fetch_korea_source", "audit_stock_information",
    "audit_preservation", "checkpoint", "publish", "status",
    "exclude_closed_price_observations", "prune_closed_sessions", "audit_calendar_prices",
    "audit_publication",
]


def main():
    baseline = ROOT / "data/tmp_2015/baseline"
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
    missing = [name for name in NAMES if not (ROOT / f"scripts/{name}_2015.py").exists()]
    if missing:
        raise RuntimeError("Restore the reviewed 2015 collectors from source control: " + ", ".join(missing))
    print("Preserved baseline; reviewed 2015 collectors are present", flush=True)


if __name__ == "__main__":
    main()
