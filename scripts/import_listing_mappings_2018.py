"""Reuse verified same-listing mappings, with original identity and provenance."""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json

from backfill_yahoo_calendars import _company_name_matches
from stock_chart_history import ROOT, write_json


def main():
    source = ROOT / 'data/tmp_2019/worktree/data/tmp_2019/mappings'
    universe = {row['symbol']: row for row in json.loads((ROOT / 'data/tmp_tradingview_chart/universe.json').read_bytes())['rows']}
    copied = []
    venues = {'PA': 'PAR', 'AS': 'AMS', 'BR': 'BRU', 'LS': 'LIS', 'IR': 'ISE'}
    for path in source.glob('*.json'):
        value = json.loads(path.read_bytes())
        listing = universe.get(value['ticker'])
        if not value.get('symbol') or not listing or len(value.get('matches', [])) != 1:
            continue
        match = value['matches'][0]
        suffix = value['symbol'].rsplit('.', 1)[-1]
        if (match['symbol'] != value['symbol'] or match['exchange'] != venues.get(suffix)
            or match['currency'].upper() != listing['currency'].upper()
            or value['symbol'].rsplit('.', 1)[0] != listing['name']
            or not _company_name_matches(listing['description'], {'longName': match['company']})):
            continue
        target = ROOT / 'data/tmp_2018/mappings' / path.name
        if target.exists():
            continue
        provenance = {'path': path.relative_to(ROOT).as_posix(), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        write_json(target, {**value, 'mapping_provenance': provenance})
        copied.append({'ticker': value['ticker'], 'yahoo_symbol': value['symbol'], **provenance})
    write_json(ROOT / 'data/information-audit/2018/reused-listing-mappings.json', {'imported': copied, 'checked_at': datetime.now(timezone.utc).isoformat()})
    print(f'Reused {len(copied)} verified exact-listing mappings')


if __name__ == '__main__':
    main()
