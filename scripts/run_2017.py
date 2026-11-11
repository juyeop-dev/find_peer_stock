"""Run one resumable 2017 job, recording its command, PID, log and exit status."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "data/tmp_2017"
PYTHON = [sys.executable, "-u"]
DATES = ["--start", "2017-01-01", "--end", "2017-12-31"]
JOBS = {
    "financials": [*PYTHON, "scripts/backfill_stock_information_2017.py", "collect", "--workers", "12"],
    "sec": [*PYTHON, "scripts/backfill_sec_financials_2017.py", "collect"],
    "semiconductor": [*PYTHON, "scripts/backfill_semiconductor_history_2017.py"],
    "korea": [*PYTHON, "scripts/backfill_korean_new_highs.py", *DATES, "--workers", "12"],
    **{market: [*PYTHON, "scripts/backfill_yahoo_calendars.py", "--market", market, *DATES, "--workers", "8"]
       for market in ["us", "japan", "china", "taiwan"]},
    "credit": [*PYTHON, "scripts/backfill_credit_2017.py"],
    "investors": ["node", "scripts/backfill_investors_2017.mjs"],
    "source": [*PYTHON, "scripts/fetch_korea_source_2017.py"],
    "europe": [*PYTHON, "scripts/backfill_european_new_highs.py", *DATES, "--daily-bars", "3200",
               "--partial-history", "--workers", "4", "--universe-cache", "data/tmp_tradingview_chart/universe.json"],
    "europe-turnover": [*PYTHON, "scripts/backfill_european_turnover.py", *DATES, "--daily-bars", "3200", "--partial-history"],
    "financial-finalize": [*PYTHON, "scripts/finalize_financials_2017.py"],
    "korea-finalize": [*PYTHON, "scripts/finalize_korea_2017.py"],
    "history": [*PYTHON, "scripts/refresh_stock_information_history.py", "--state-dir", "data/tmp_2017_history", "--import-chart-cache", "--extend-to-start"],
    "extend": [*PYTHON, "scripts/extend_stock_history_2017.py"],
    "history-audit": [*PYTHON, "scripts/complete_history_audit_2017.py"],
    "taiwan-bases": [*PYTHON, "scripts/prepare_taiwan_2017.py"],
    "taiwan-gap": [*PYTHON, "scripts/recover_taiwan_official_2017.py"],
    "rebounds": [*PYTHON, "scripts/backfill_rebounds.py", *DATES, "--deps-dir", "data/tmp_korea_recalculation/deps"],
}


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in JOBS:
        raise SystemExit("Choose one job: " + ", ".join(JOBS))
    name = sys.argv[1]
    STATE.mkdir(parents=True, exist_ok=True)
    record = STATE / f"{name}.process.json"
    # A cross-process exclusive lock prevents duplicate collectors, including
    # the interval between launching the child and writing its PID record.
    lock = STATE / f"{name}.lock"
    with lock.open("x"):
        pass
    value = {"pid": os.getpid(), "command": JOBS[name], "started_at": datetime.now(timezone.utc).isoformat()}
    record.write_text(json.dumps(value, indent=2), encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": str(ROOT / "data/tmp_info_update/deps"), "PYTHONIOENCODING": "utf-8"}
    try:
        with (STATE / f"{name}.log").open("ab", buffering=0) as output:
            child = subprocess.Popen(JOBS[name], cwd=ROOT, stdout=output, stderr=subprocess.STDOUT, env=env)
            value["child_pid"] = child.pid
            record.write_text(json.dumps(value, indent=2), encoding="utf-8")
            code = child.wait()
        value.update(exit_code=code, finished_at=datetime.now(timezone.utc).isoformat())
        record.write_text(json.dumps(value, indent=2), encoding="utf-8")
        print(f"{name}: exit={code}", flush=True)
        raise SystemExit(code)
    finally:
        lock.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
