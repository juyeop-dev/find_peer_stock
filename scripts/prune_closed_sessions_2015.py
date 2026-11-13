"""Exclude provider holiday/off-book bars using the documented exchange schedule."""
from pathlib import Path
import json
from stock_chart_history import ROOT, write_json


def main():
    config = json.loads((ROOT / 'data/market-closures/2015.json').read_bytes())
    baseline = json.loads((ROOT / 'data/tmp_2015/baseline/manifest.json').read_bytes())['original_daily_sha256']
    removed = []
    for market in config['markets']:
        for kind in ['new-highs', 'turnover']:
            namespace = ROOT / 'data' / kind / 'reports' / market['market']
            for path in namespace.rglob('2015-*.json'):
                if path.stem not in market['dates']:
                    continue
                relative = path.relative_to(ROOT).as_posix()
                if relative in baseline:
                    raise ValueError(f'Cannot remove a pre-update original: {relative}')
                value = json.loads(path.read_bytes())
                if value['date'] != path.stem or value['market'] != market['market']:
                    raise ValueError('Unexpected report identity')
                removed.append({'path': relative, 'reason': market['dates'][path.stem], 'sources': market['source_urls']})
                path.unlink()
    write_json(ROOT / 'data/information-audit/2015/excluded-holiday-observations.json', {'excluded': removed})
    print(f'Excluded {len(removed)} newly collected holiday/off-book reports; all prior-year originals retained')


if __name__ == '__main__':
    main()
