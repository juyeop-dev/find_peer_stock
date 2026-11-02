"""Apply existing lossless report publication to completed H1-2026 archives."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path

from archive_paths import publish_daily_report
from stock_chart_history import ROOT, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, default=ROOT)
    args = parser.parse_args()
    public = args.project.resolve() / 'frontend/public/data'
    proofs = []
    for namespace in ['new-highs', 'turnover']:
        for path in (public / namespace).rglob('2026-*.json'):
            if not '2026-01-01' <= path.stem < '2026-07-01':
                continue
            original = path.read_bytes()
            payload = json.loads(original)
            publish_daily_report(path, payload, public)
            encoded = path.with_suffix('.json.gz').read_bytes()
            decoded = gzip.decompress(encoded)
            assert json.loads(decoded) == payload
            assert decoded == original, 'Published report bytes must remain exact'
            proofs.append({'path': path.relative_to(public).as_posix(), 'original_sha256': hashlib.sha256(original).hexdigest(),
                           'original_bytes': len(original), 'compressed_bytes': len(encoded)})
    write_json(args.project / 'data/information-audit/2018/public-report-compaction.json',
               {'before': '2026-07-01', 'verified_reports': len(proofs),
                'saved_bytes': sum(row['original_bytes']-row['compressed_bytes'] for row in proofs), 'reports': proofs})
    print(f'Losslessly compacted {len(proofs)} verified public reports')


if __name__ == '__main__':
    main()
