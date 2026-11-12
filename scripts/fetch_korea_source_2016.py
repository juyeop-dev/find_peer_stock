"""Cache a revision-pinned KRX daily amount/capitalization mirror and checksum."""
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
import hashlib
import json

ROOT = Path(__file__).resolve().parents[1]
REVISION = 'eeed0817d1478597b738a3a6149c170ec7e3f4cb'
URL = f'https://raw.githubusercontent.com/FinanceData/marcap/{REVISION}/data/marcap-2016.parquet'


def main():
    path = ROOT / 'data/tmp_korea_recalculation/source/marcap-2016.parquet'
    metadata = path.with_suffix('.source.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and metadata.exists():
        assert hashlib.sha256(path.read_bytes()).hexdigest() == json.loads(metadata.read_bytes())['sha256']
        print('Verified cached 2016 KRX mirror')
        return
    with urlopen(Request(URL, headers={'User-Agent': 'Stock Study historical research'}), timeout=90) as response:
        raw = response.read()
    if raw[:4] != b'PAR1' or raw[-4:] != b'PAR1':
        raise ValueError('Source is not a Parquet file')
    path.write_bytes(raw)
    metadata.write_text(json.dumps({'year': 2016, 'url': URL, 'revision': REVISION,
        'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
        'fetched_at': datetime.now(timezone.utc).isoformat()}, indent=2)+'\n', encoding='utf-8')
    print(f'Cached {len(raw)} bytes of original 2016 KRX daily data')


if __name__ == '__main__':
    main()
