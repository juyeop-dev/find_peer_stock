"""Extend replay curves from originals while retaining every pre-update curve."""
from datetime import datetime, timezone
from pathlib import Path
import json
import shutil

import refresh_chart_replay as replay
from stock_chart_history import write_json


def main():
    backup = replay.ROOT / 'data/tmp_2017/baseline/chart-replay/markets.json'
    backup.parent.mkdir(parents=True, exist_ok=True)
    if not backup.exists():
        shutil.copy2(replay.SNAPSHOT, backup)
    previous = json.loads(replay.SNAPSHOT.read_bytes())
    originals = [replay.collect_kospi(), replay.collect(*replay.SYMBOLS[1])]
    histories = []
    for fresh in originals:
        old = next(row for row in previous['markets'] if row['ticker'] == fresh['ticker'])
        stored = {bar['date']: bar for bar in old['bars']}
        overlap = [bar for bar in fresh['bars'] if bar['date'] in stored]
        if len(overlap) >= 3 and fresh['currency'] == old['currency'] and all(stored[bar['date']] == bar for bar in overlap):
            histories.append({**old, 'bars': [bar for bar in fresh['bars'] if bar['date'] < old['bars'][0]['date']] + old['bars']})
        else:
            histories.append({**fresh, 'prior_snapshots': [*old.get('prior_snapshots', []), old]})
    result = {**previous, 'fetched_at': datetime.now(timezone.utc).isoformat(), 'markets': histories}
    write_json(replay.SNAPSHOT, result)
    write_json(replay.PUBLIC, result)
    print({row['ticker']: {'first': row['bars'][0]['date'], 'observations': len(row['bars'])} for row in histories})


if __name__ == '__main__':
    main()
