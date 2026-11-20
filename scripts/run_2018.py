"""Launch resumable 2018 source collectors with per-job logs and PID records."""
from pathlib import Path
from datetime import datetime, timezone
import json
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / 'data/tmp_2018'
JOBS = {
    'financials': [sys.executable, '-u', 'scripts/backfill_stock_information_2018.py', 'collect', '--workers', '12'],
    'sec': [sys.executable, '-u', 'scripts/backfill_sec_financials_2018.py', 'collect'],
    'semiconductor': [sys.executable, '-u', 'scripts/backfill_semiconductor_history_2018.py'],
    'korea': [sys.executable, '-u', 'scripts/backfill_korean_new_highs.py', '--start', '2018-01-01', '--end', '2018-12-31', '--workers', '12'],
    **{market: [sys.executable, '-u', 'scripts/backfill_yahoo_calendars.py', '--market', market, '--start', '2018-01-01', '--end', '2018-12-31', '--workers', '8'] for market in ['us', 'japan', 'china', 'taiwan']},
    'credit': [sys.executable, '-u', 'scripts/backfill_credit_2018.py'],
    'investors': ['node', 'scripts/backfill_investors_2018.mjs'],
    'europe': [sys.executable, '-u', 'scripts/backfill_european_new_highs.py', '--start', '2018-01-01', '--end', '2018-12-31', '--daily-bars', '2800', '--partial-history', '--universe-cache', 'data/tmp_tradingview_chart/universe.json'],
    'europe-turnover': [sys.executable, '-u', 'scripts/backfill_european_turnover.py', '--start', '2018-01-01', '--end', '2018-12-31', '--daily-bars', '2800', '--partial-history'],
    'financial-finalize': [sys.executable, '-u', 'scripts/finalize_financials_2018.py'],
    'korea-finalize': [sys.executable, '-u', 'scripts/finalize_korea_2018.py'],
    'taiwan-gap': [sys.executable, '-u', 'scripts/recover_taiwan_official_2018.py'],
    'history': [sys.executable, '-u', 'scripts/refresh_stock_information_history.py', '--state-dir', 'data/tmp_2018_history', '--extend-to-start'],
}


def main(argv=None):
    from history_jobs import legacy_main
    legacy_main(JOBS, year=2018, argv=argv, root=ROOT, dependencies={"europe-turnover": ["europe"]})


if __name__ == '__main__':
    main()
