"""Supplement missing 2021 annuals with explicitly verified issuer statements."""
import json
from datetime import datetime, timezone
import backfill_stock_information_2021 as config
import backfill_stock_information_2024_h2 as recovery


def main():
    config.configure()
    db = recovery.info.open_database(recovery.STATE)
    now = datetime.now(timezone.utc).isoformat()
    seed = json.loads((recovery.info.ROOT / 'data/seed/reported_financials_2021.json').read_bytes())
    applied = []
    for row in seed['statements']:
        assert row['currency'] == 'USD' and row['multiplier'] == 1000000
        assert recovery.START <= row['period_end'] <= recovery.END
        ticker = row['ticker']
        old = json.loads(db.execute('SELECT value FROM information WHERE ticker=?', (ticker,)).fetchone()[0])
        if any(s['type'] == 'annual' and s['period_end'] == row['period_end'] for s in old.get('financials', [])):
            continue
        statement = {key: row[key] * row['multiplier'] if key in row else None for key in recovery.info.METRICS}
        statement.update(type='annual', period_end=row['period_end'], currency=row['currency'],
            source='Issuer published GAAP annual statement', source_url=row['source_url'],
            fiscal_label=row['fiscal_label'], published_at=row['published_at'])
        value = recovery.merge(old, [statement], now)
        result = {'queried_at': now, 'status': 'available', **value[recovery.COVERAGE_KEY], 'errors': [],
                  'supplement_source': row['source_url']}
        db.execute('INSERT OR REPLACE INTO information VALUES (?,?)', (ticker, json.dumps(value, ensure_ascii=False, separators=(',', ':'))))
        db.execute(f'INSERT OR REPLACE INTO {recovery.TABLE} VALUES (?,?)', (ticker, json.dumps(result)))
        applied.append(ticker)
    db.commit()
    recovery.checkpoint(db, recovery.charts.roster())
    recovery.charts.write_json(recovery.AUDIT / 'issuer-supplement.json', {'applied': applied, 'checked_at': now, **seed})
    print('Issuer statements:', applied)


if __name__ == '__main__':
    main()
