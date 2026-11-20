"""Run one resumable 2014 job, recording its command, PID, log and exit status."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "data/tmp_2014"
PYTHON = [sys.executable, "-u"]
DATES = ["--start", "2014-01-01", "--end", "2014-12-31"]
JOBS = {
    "taiwan-bases": [*PYTHON, "scripts/prepare_taiwan_2014.py"],
    "taiwan-gap": [*PYTHON, "scripts/recover_taiwan_official_2014.py"],
    "financials": [*PYTHON, "scripts/backfill_stock_information_2014.py", "collect", "--workers", "12"],
    "sec": [*PYTHON, "scripts/backfill_sec_financials_2014.py", "collect"],
    "semiconductor": [*PYTHON, "scripts/backfill_semiconductor_history_2014.py"],
    "replay": [*PYTHON, "scripts/backfill_chart_replay_2014.py"],
    "korea": [*PYTHON, "scripts/backfill_korean_new_highs.py", *DATES, "--workers", "12"],
    **{market: [*PYTHON, "scripts/backfill_yahoo_calendars.py", "--market", market, *DATES, "--workers", "8"]
       for market in ["us", "japan", "china", "taiwan"]},
    "credit": [*PYTHON, "scripts/backfill_credit_2014.py"],
    "investors": ["node", "scripts/backfill_investors_2014.mjs"],
    "source": [*PYTHON, "scripts/fetch_korea_source_2014.py"],
    "europe": [*PYTHON, "scripts/backfill_european_new_highs.py", *DATES, "--daily-bars", "3700",
               "--partial-history", "--workers", "4", "--universe-cache", "data/tmp_tradingview_chart/universe.json"],
    "europe-turnover": [*PYTHON, "scripts/backfill_european_turnover.py", *DATES, "--daily-bars", "3700", "--partial-history"],
    "financial-finalize": [*PYTHON, "scripts/finalize_financials_2014.py"],
    "korea-finalize": [*PYTHON, "scripts/finalize_korea_2014.py"],
    "history": [*PYTHON, "scripts/refresh_stock_information_history.py", "--state-dir", "data/tmp_2014_history", "--import-chart-cache", "--extend-to-start"],
    "extend": [*PYTHON, "scripts/extend_stock_history_2014.py"],
    "history-audit": [*PYTHON, "scripts/complete_history_audit_2014.py"],
    "rebounds": [*PYTHON, "scripts/backfill_rebounds.py", *DATES, "--deps-dir", "data/tmp_korea_recalculation/deps"],
}


def main(argv=None):
    from history_jobs import legacy_main
    legacy_main(JOBS, year=2014, argv=argv, root=ROOT, dependencies={"taiwan-gap": ["taiwan", "taiwan-bases"], "europe-turnover": ["europe"]})


if __name__ == "__main__":
    main()
