"""Prepare isolated 2018 collectors and an immutable pre-update baseline."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import re
import shutil

ROOT = Path(__file__).resolve().parents[1]


def main():
    state = ROOT / 'data/tmp_2018'
    baseline = state / 'baseline'
    baseline.mkdir(parents=True, exist_ok=True)
    manifest = baseline / 'manifest.json'
    if not manifest.exists():
        hashes = {}
        for namespace in ['new-highs/reports', 'turnover/reports', 'sectors/daily']:
            for path in (ROOT / 'data' / namespace).rglob('*'):
                if path.is_file():
                    hashes[path.relative_to(ROOT).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
        for namespace in ['stock-information', 'stock-history', 'semiconductor', 'investors', 'credit', 'generated/stocks']:
            source = ROOT / 'data' / namespace
            shutil.copytree(source, baseline / namespace)
        manifest.write_text(json.dumps({'created_at': datetime.now(timezone.utc).isoformat(), 'original_daily_sha256': hashes}, indent=2), encoding='utf-8')
    names = ['backfill_stock_information', 'extend_stock_history', 'backfill_credit',
             'backfill_sector_history', 'backfill_semiconductor_history', 'backfill_sec_financials',
             'audit_calendar', 'audit_stock_information', 'audit_preservation', 'finalize_financials', 'finalize_korea']
    for name in names:
        target = ROOT / f'scripts/{name}_2018.py'
        if not target.exists():
            source = (ROOT / f'scripts/{name}_2019.py').read_text(encoding='utf-8')
            # Shift all dates simultaneously, including the prior-year buffer and SEC frames.
            source = re.sub(r'(?<!\d)(?:2018|2019|2020)(?!\d)', lambda match: str(int(match[0])-1), source)
            source = source.replace('_2019', '_2018').replace('2026-10-30-2018', '2026-11-02-2018')
            target.write_text(source, encoding='utf-8')
    target = ROOT / 'scripts/backfill_investors_2018.mjs'
    if not target.exists():
        target.write_text((ROOT / 'scripts/backfill_investors_2019.mjs').read_text(encoding='utf-8').replace('2019', '2018'), encoding='utf-8')
    print('2018 collectors and original-data baseline prepared', flush=True)


if __name__ == '__main__':
    main()
