"""Extend replay curves from originals while retaining every pre-update curve."""
from datetime import datetime, timezone
from pathlib import Path
import json
import shutil
import argparse
from dataclasses import asdict
from collection_request import collection_request
from price_history_range import load_price_range
from history_policy import DEFAULT_POLICY

import refresh_chart_replay as replay
from stock_chart_history import write_json


def main(argv=None, *, year=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, default=year)
    parser.add_argument("--history-config", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        request = collection_request(year=args.year, config=args.history_config, root=replay.ROOT, through_present=args.year is not None)
        price_request = load_price_range(args.history_config, year=args.year, through_present=args.year is not None)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    backup = request.state / 'baseline/chart-replay/markets.json'
    if args.dry_run:
        print(json.dumps({**asdict(request), "backup": str(backup)}, default=str)); return
    backup.parent.mkdir(parents=True, exist_ok=True)
    if not backup.exists():
        shutil.copy2(replay.SNAPSHOT, backup)
    previous = json.loads(replay.SNAPSHOT.read_bytes())
    originals = [replay.collect_kospi(price_request), replay.collect(*replay.SYMBOLS[1], price_request)]
    histories = []
    for fresh in originals:
        old = next(row for row in previous['markets'] if row['ticker'] == fresh['ticker'])
        stored = {bar['date']: bar for bar in old['bars']}
        overlap = [bar for bar in fresh['bars'] if bar['date'] in stored]
        if len(overlap) >= 3 and fresh['currency'] == old['currency'] and all(stored[bar['date']] == bar for bar in overlap):
            histories.append({**old, **{key: value for key, value in fresh.items() if key != 'bars'},
                'bars': [bar for bar in fresh['bars'] if bar['date'] < old['bars'][0]['date']] + old['bars']
                      + [bar for bar in fresh['bars'] if bar['date'] > old['bars'][-1]['date']]})
        else:
            histories.append({**fresh, 'prior_snapshots': [*old.get('prior_snapshots', []), old]})
    result = {**previous, 'fetched_at': datetime.now(timezone.utc).isoformat(), 'markets': histories}
    write_json(replay.SNAPSHOT, result)
    write_json(replay.PUBLIC, result)
    print({row['ticker']: {'first': row['bars'][0]['date'], 'observations': len(row['bars'])} for row in histories})


if __name__ == '__main__':
    main()
