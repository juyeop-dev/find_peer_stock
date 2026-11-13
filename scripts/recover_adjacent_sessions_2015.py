"""Recompute adjacent high/turnover reports, including filters, on one price basis."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

from archive_paths import monthly_report_path
from stock_chart_history import ROOT, write_json

DATES = {"japan": ("2015-12-25", "2015-12-28"), "china": ("2015-02-25", "2015-02-26")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("market", choices=DATES)
    args = parser.parse_args()
    first, adjacent = DATES[args.market]
    audit = ROOT / "data/information-audit/2015"
    proof = audit / f"{args.market}-gap-recovery.json"
    original = json.loads(proof.read_bytes())
    assert original["date"] == first
    backup = ROOT / f"data/tmp_2015/{args.market}-replaced-reports"
    backup.mkdir(parents=True, exist_ok=True)
    for kind in ["new-highs", "turnover"]:
        path = ROOT / f"data/new-highs/reports/{args.market}/{adjacent}.json" if kind == "new-highs" else monthly_report_path(ROOT / "data/turnover/reports", args.market, adjacent)
        target = backup / f"{kind}-{adjacent}.json"
        if not target.exists():
            target.write_bytes(path.read_bytes())
    try:
        subprocess.run([sys.executable, "-u", str(ROOT / f"scripts/recover_{args.market}_session_2015.py"), "--date", adjacent], check=True)
        second = json.loads(proof.read_bytes())
        assert second["date"] == adjacent
        write_json(audit / f"{args.market}-adjacent-source.json", second)
    finally:
        write_json(proof, original)
    print(f"Recomputed {args.market} {adjacent} high filters, classifications and turnover on coherent actual prices", flush=True)


if __name__ == "__main__":
    main()
