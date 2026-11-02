"""Publish the verified local history while retaining current quote snapshots."""
from pathlib import Path
import json
import subprocess
import sys

import stock_chart_history as charts
import stock_information as info


def main():
    for name in ['generate_new_high_data.py', 'generate_turnover_data.py', 'generate_calendar_stock_data.py']:
        subprocess.run([sys.executable, 'scripts/'+name], check=True)
    charts.publish()
    info.sync_primary_snapshots = lambda values: None
    info.publish()
    source = json.loads((charts.ROOT / 'data/semiconductor/index.json').read_bytes())
    path = charts.ROOT / 'frontend/public/data/semiconductor/index.json'
    current = json.loads(path.read_bytes())
    histories = {row['ticker']: row for row in source['stocks']}
    for stock in current['stocks']:
        value = histories[stock['ticker']]
        previous = stock.get('history', [])
        curves = [value['history'], *[snapshot['history'] for snapshot in value.get('prior_history_snapshots', [])]]
        available = {json.dumps(point, sort_keys=True) for curve in curves for point in curve}
        snapshots = list(value.get('prior_history_snapshots', []))
        if any(json.dumps(point, sort_keys=True) not in available for point in previous):
            snapshots.append({'history': previous, 'preservation_reason': 'Pre-update public curve retained separately'})
        if snapshots:
            charts.write_json(charts.ROOT / f'data/tmp_2018/public-semiconductor-preservation/{stock["ticker"]}.json',
                              {'ticker': stock['ticker'], 'prior_history_snapshots': snapshots})
        stock.pop('prior_history_snapshots', None)
        stock.update(history=value['history'],
                     historical_2018_extension=value['historical_2018_extension'])
    charts.write_json(path, current)
    for name in ['refresh_sectors.mjs', 'refresh_investors.mjs']:
        subprocess.run(['node', 'scripts/'+name, 'publish'], check=True)
    print('Published local 2018 data; current global quotes and peer snapshots retained', flush=True)


if __name__ == '__main__':
    main()
