"""Prove all pre-expansion observations remain current or as original snapshots."""
import gzip
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import stock_chart_history as charts


def unpack(path):
    return json.loads(gzip.decompress(path.read_bytes()))


def main():
    baseline = charts.ROOT / 'data/tmp_2016/baseline'
    result = {'checked_at': datetime.now(timezone.utc).isoformat()}
    sources = json.loads((baseline / 'manifest.json').read_bytes())['original_daily_sha256']
    for relative, digest in sources.items():
        assert hashlib.sha256((charts.ROOT / relative).read_bytes()).hexdigest() == digest, relative
    result['unchanged_source_files'] = len(sources)
    snapshots = list((baseline / 'generated/stocks').glob('*.json'))
    for path in snapshots:
        assert path.read_bytes() == (charts.ROOT / 'data/generated/stocks' / path.name).read_bytes(), path.name
    result['unchanged_current_stock_snapshots'] = len(snapshots)
    for kind in ['credit', 'investors']:
        old = json.loads((baseline / kind / 'index.json').read_bytes())
        new = json.loads((charts.ROOT / 'data' / kind / 'index.json').read_bytes())
        current = {row['date']: row for row in new['history']}
        assert all(current.get(row['date']) == row for row in old['history']), kind
        result[f'{kind}_unchanged_rows'] = len(old['history'])
    listings, statements, points = 0, 0, 0
    for path in sorted((baseline / 'stock-information').glob('*.gz')):
        old, new = unpack(path), unpack(charts.ROOT / 'data/stock-information' / path.name)
        for ticker, value in old.items():
            assert ticker in new, ticker
            for statement in value.get('financials', []):
                assert statement in new[ticker]['financials'], (ticker, statement)
                statements += 1
            listings += 1
    result.update(prior_financial_listings=listings, unchanged_reported_statements=statements)
    for path in sorted((baseline / 'stock-history').glob('*.gz')):
        old, new = unpack(path), unpack(charts.ROOT / 'data/stock-history' / path.name)
        for ticker, value in old.items():
            current = new[ticker]
            curves = [current, *current.get('prior_snapshots', [])]
            retained = {tuple(point) for curve in curves if curve['currency'] == value['currency'] for point in curve['prices']}
            assert all(tuple(point) in retained for point in value['prices']), ticker
            points += len(value['prices'])
            for snapshot in value.get('prior_snapshots', []):
                retained = {tuple(point) for curve in curves if curve['currency'] == snapshot['currency'] for point in curve['prices']}
                assert all(tuple(point) in retained for point in snapshot['prices']), (ticker, 'prior snapshot')
    result['preserved_prior_price_points'] = points
    old = json.loads((baseline / 'semiconductor/index.json').read_bytes())
    new = json.loads((charts.ROOT / 'data/semiconductor/index.json').read_bytes())
    assert len(old['stocks']) == len(new['stocks'])
    for prior in old['stocks']:
        current = next(row for row in new['stocks'] if row['ticker'] == prior['ticker'])
        for key, value in prior.items():
            if key == 'history':
                curves = [current['history'], *[s['history'] for s in current.get('prior_history_snapshots', [])]]
                retained = {json.dumps(point, sort_keys=True) for curve in curves for point in curve}
                assert all(json.dumps(point, sort_keys=True) in retained for point in value), prior['ticker']
            elif key == 'prior_history_snapshots':
                assert all(snapshot in current[key] for snapshot in value), prior['ticker']
            else:
                assert current[key] == value, (prior['ticker'], key)
    result['preserved_semiconductor_listings'] = len(old['stocks'])
    old_replay = json.loads((baseline / 'chart-replay/markets.json').read_bytes())
    new_replay = json.loads((charts.ROOT / 'data/chart-replay/markets.json').read_bytes())
    replay_bars = 0
    for prior in old_replay['markets']:
        current = next(row for row in new_replay['markets'] if row['ticker'] == prior['ticker'])
        curves = [current, *current.get('prior_snapshots', [])]
        retained = {json.dumps(bar, sort_keys=True) for curve in curves if curve['currency'] == prior['currency'] for bar in curve['bars']}
        for curve in [prior, *prior.get('prior_snapshots', [])]:
            assert all(json.dumps(bar, sort_keys=True) in retained for bar in curve['bars']), prior['ticker']
            replay_bars += len(curve['bars'])
    result['preserved_replay_bars'] = replay_bars
    charts.write_json(charts.ROOT / 'data/information-audit/2016/preservation.json', result)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
