"""Read lossless artifact encodings without changing canonical source values."""
from datetime import date, timedelta
import gzip
import json


def expand_price_archive(value):
    if not isinstance(value, dict) or 'encoding' not in value:
        return value
    if value['encoding'] != 'stock-history-delta-v1':
        raise ValueError('Unknown price archive encoding')

    def curve(item):
        result = dict(item)
        start = result.pop('price_start')
        rows = result['prices']
        day = date.fromisoformat(start) if rows else None
        if not rows and start is not None:
            raise ValueError('Empty curve has a start date')
        restored = []
        for index, row in enumerate(rows):
            if len(row) not in (2, 3) or type(row[0]) is not int or (row[0] != 0 if index == 0 else row[0] <= 0):
                raise ValueError('Invalid observation date gap')
            day += timedelta(days=row[0])
            restored.append([day.isoformat(), row[1], row[2] if len(row) == 3 else row[1]])
        result['prices'] = restored
        if 'prior_snapshots' in result:
            result['prior_snapshots'] = [curve(prior) for prior in result['prior_snapshots']]
        return result

    return curve({key: item for key, item in value.items() if key != 'encoding'})


def load(path):
    if not path.exists() and not path.name.endswith('.gz'):
        path = path.with_name(path.name + '.gz')
    if not path.exists() and path.parent.name == 'stock-history' and path.name.endswith('.json.gz'):
        path = path.with_name(path.name.removesuffix('.json.gz') + '.delta-v1.json.gz')
    raw = path.read_bytes()
    value = json.loads(gzip.decompress(raw) if raw[:2] == b'\x1f\x8b' else raw)
    if isinstance(value, dict) and value.get('encoding') == 'sector-columns-v1':
        fields = value.pop('stock_fields')
        rows = value.pop('stock_rows')
        value.pop('encoding')
        value['stocks'] = [dict(zip(fields[row[0]], row[1:], strict=True)) for row in rows]
        return value
    return expand_price_archive(value)
