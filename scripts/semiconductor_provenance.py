"""Store private original semiconductor curves in verified immutable gzip files."""
import gzip
import hashlib
import json
from pathlib import Path
from urllib.parse import quote

REFERENCE = 'prior_history_archive'


def hydrate_semiconductor(value, directory):
    directory = Path(directory).resolve()
    stocks = []
    for original in value.get('stocks', []):
        row = dict(original)
        reference = row.pop(REFERENCE, None)
        if reference is not None:
            archive = (directory / reference['file']).resolve()
            if not archive.is_relative_to(directory / 'preserved-snapshots'):
                raise ValueError('Provenance archive leaves its designated source directory')
            raw = archive.read_bytes()
            if hashlib.sha256(raw).hexdigest() != reference['sha256']:
                raise ValueError('Original semiconductor archive checksum differs')
            payload = json.loads(gzip.decompress(raw))
            if payload['ticker'] != row['ticker'] or len(payload['prior_history_snapshots']) != reference['snapshots']:
                raise ValueError('Original semiconductor archive identity differs')
            row['prior_history_snapshots'] = payload['prior_history_snapshots'] + row.get('prior_history_snapshots', [])
        stocks.append(row)
    return {**value, 'stocks': stocks}


def archive_semiconductor(value, directory):
    directory = Path(directory).resolve()
    expanded = hydrate_semiconductor(value, directory)
    stocks = []
    for original in expanded.get('stocks', []):
        row = dict(original)
        snapshots = row.pop('prior_history_snapshots', None)
        if snapshots:
            payload = {'ticker': row['ticker'], 'prior_history_snapshots': snapshots}
            raw = (json.dumps(payload, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n').encode()
            encoded = gzip.compress(raw, compresslevel=9, mtime=0)
            assert json.loads(gzip.decompress(encoded)) == payload
            digest = hashlib.sha256(encoded).hexdigest()
            filename = quote(row['ticker'], safe='').replace('%', '~') + '.' + digest[:20] + '.json.gz'
            relative = Path('preserved-snapshots') / filename
            target = directory / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                assert target.read_bytes() == encoded
            else:
                temporary = target.with_suffix(target.suffix + '.tmp')
                temporary.write_bytes(encoded)
                temporary.replace(target)
            row[REFERENCE] = {'file': relative.as_posix(), 'sha256': digest, 'snapshots': len(snapshots)}
        elif snapshots is not None:
            row['prior_history_snapshots'] = snapshots
        stocks.append(row)
    return {**expanded, 'stocks': stocks}
