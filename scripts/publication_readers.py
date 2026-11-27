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
    if isinstance(value, dict) and value.get('encoding') == 'sector-week-v1':
        return value
    if isinstance(value, dict) and value.get('encoding') == 'sector-columns-v1':
        fields = value.pop('stock_fields')
        rows = value.pop('stock_rows')
        value.pop('encoding')
        value['stocks'] = [dict(zip(fields[row[0]], row[1:], strict=True)) for row in rows]
        return value
    return expand_price_archive(value)


def load_sector_listing(path):
    snapshot = load(path)
    return {**snapshot, 'stocks': [
        {key: value for key, value in stock.items() if key not in ('returns', 'change_pct')}
        for stock in snapshot['stocks']
    ]}


def load_published_sector_day(directory, day):
    session = date.fromisoformat(day)
    monday = session - timedelta(days=session.weekday())
    weekly = directory / 'weekly' / f'{monday}.json.gz'
    if not weekly.is_file():
        return load(directory / 'daily' / f'{day}.json.gz')
    bundle = load(weekly)
    if bundle.get('encoding') != 'sector-week-v1':
        raise ValueError('Unknown sector week encoding')
    day_index, (header, *order) = next((i, values) for i, values in enumerate(bundle['days']) if values[0]['date'] == day)
    fields = ('price', 'turnover', 'market_cap', 'date', 'market_cap_date')
    stocks = {}
    for profile, mask, observations in bundle['profiles']:
        row = next((values[1:] for values in observations if values[0] == day_index), None)
        if row is None:
            continue
        values = {key: day if i >= 3 and value == 1 else value
                  for i, (key, value) in enumerate(zip(fields, row, strict=True)) if mask & (1 << i)}
        stocks[profile['ticker']] = {**profile, **values}
    return {**header, 'stocks': [stocks[ticker] for ticker in (order[0] if order else sorted(stocks))]}
