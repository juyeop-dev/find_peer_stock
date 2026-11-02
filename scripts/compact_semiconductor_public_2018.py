"""Keep public semiconductor charts complete and archive unused preservation copies."""
import gzip
import hashlib
import json

from stock_chart_history import ROOT, write_json


def main():
    path = ROOT / 'frontend/public/data/semiconductor/index.json'
    original = path.read_bytes()
    value = json.loads(original)
    copies = {row['ticker']: row['prior_history_snapshots'] for row in value['stocks'] if row.get('prior_history_snapshots')}
    if copies:
        archive = ROOT / 'data/semiconductor/public-preserved-curves-2018.json.gz'
        body = json.dumps(copies, ensure_ascii=False, separators=(',',':'), allow_nan=False).encode()
        encoded = gzip.compress(body, compresslevel=9, mtime=0)
        assert json.loads(gzip.decompress(encoded)) == copies
        archive.write_bytes(encoded)
        for row in value['stocks']:
            row.pop('prior_history_snapshots', None)
        write_json(path, value)
        write_json(ROOT / 'data/information-audit/2018/public-semiconductor-preservation.json',
            {'original_public_sha256': hashlib.sha256(original).hexdigest(), 'archive_sha256': hashlib.sha256(encoded).hexdigest(),
             'archive': archive.relative_to(ROOT).as_posix(), 'listings': len(copies),
             'complete_primary_histories': len(value['stocks']), 'original_bytes': len(original), 'public_bytes': path.stat().st_size})
    print(f'Published {len(value["stocks"])} complete primary histories, {path.stat().st_size/2**20:.2f} MiB')


if __name__ == '__main__':
    main()
