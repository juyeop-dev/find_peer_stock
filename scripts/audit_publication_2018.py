"""Verify every published 2018 report and the complete semiconductor curves."""
import argparse
import gzip
import json
from pathlib import Path

from stock_chart_history import ROOT, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, default=ROOT)
    args = parser.parse_args()
    root = args.project.resolve()
    public = root / 'frontend/public/data'
    counts = {}
    for kind in ['new-highs', 'turnover']:
        count = 0
        for path in (root / 'data/generated' / kind).rglob('2018-*.json'):
            relative = path.relative_to(root / 'data/generated')
            target = public / relative.with_suffix('.json.gz')
            assert json.loads(gzip.decompress(target.read_bytes())) == json.loads(path.read_bytes()), relative
            count += 1
        assert count == 1486, (kind, count)
        counts[kind] = count
    source = json.loads((root / 'data/semiconductor/index.json').read_bytes())
    published = json.loads((public / 'semiconductor/index.json').read_bytes())
    by_ticker = {row['ticker']: row for row in published['stocks']}
    for row in source['stocks']:
        assert by_ticker[row['ticker']]['history'] == row['history'], row['ticker']
    counts['complete_semiconductor_histories'] = len(by_ticker)
    files = [path for path in (root / 'frontend/dist').rglob('*') if path.is_file()]
    counts.update(artifact_files=len(files), artifact_bytes=sum(path.stat().st_size for path in files))
    if files:
        assert counts['artifact_bytes'] < 1024**3, counts
    write_json(root / 'data/information-audit/2018/publication.json', counts)
    print(json.dumps(counts))


if __name__ == '__main__':
    main()
