"""Import complete coherent same-listing curves containing Taiwan's missing day."""
import hashlib
import json
from datetime import datetime, timezone
import stock_chart_history as charts
from backfill_yahoo_calendars import archive_ticker
from backfill_european_new_highs import chart_bars


def main():
    charts.DATABASE = charts.ROOT / 'data/tmp_2021_history/history.sqlite'
    db = charts.database()
    universe = json.loads((charts.ROOT / 'data/tmp_2021/taiwan-gap-universe.json').read_bytes())
    imported, archived = [], []
    for row in universe['rows']:
        digest = hashlib.sha256(f"{row['symbol']}:1D:2000".encode()).hexdigest()
        path = charts.ROOT / 'data/tmp_tradingview_chart/1D' / f'{digest}.json'
        if not path.exists():
            continue
        payload = json.loads(path.read_bytes())
        try:
            bars = chart_bars(payload, row)
            if not any(str(bar.day) == '2021-04-06' for bar in bars):
                continue
            value = charts.parse_tradingview(payload, row['symbol'])
        except ValueError:
            continue
        ticker = archive_ticker(row)
        oldraw = db.execute('SELECT value FROM history WHERE ticker=?', (ticker,)).fetchone()
        if not oldraw:
            continue
        old = json.loads(oldraw[0])
        value.update(ticker=ticker, requested_bars=2000, source_symbol=row['symbol'],
            first_trade_date=old.get('first_trade_date'), fetched_at=datetime.now(timezone.utc).isoformat())
        value['prices'] = [point for point in value['prices'] if point[0] >= '2020-12-20']
        if value['prices'][-1][0] < old['prices'][-1][0]:
            # A newer current quote must remain current. Retain the complete
            # alternate observed curve separately without splicing conventions.
            snapshot = {key: value[key] for key in ['ticker', 'currency', 'source', 'fetched_at', 'prices']}
            snapshot['preservation_reason'] = 'Verified complete alternate curve containing 2021-04-06; current source has a later last quote'
            snapshots = old.get('prior_snapshots', [])
            if not any(s.get('prices') == snapshot['prices'] and s.get('source') == snapshot['source'] for s in snapshots):
                old['prior_snapshots'] = [*snapshots, snapshot]
                db.execute('UPDATE history SET value=? WHERE ticker=?', (json.dumps(old, ensure_ascii=False, separators=(',', ':')), ticker))
            archived.append(ticker)
            continue
        charts.save_candidate(db, value)
        stored = json.loads(db.execute('SELECT value FROM history WHERE ticker=?', (ticker,)).fetchone()[0])
        assert any(point[0] == '2021-04-06' for point in stored['prices']), ticker
        imported.append(ticker)
    db.commit()
    charts.export_packs(db)
    charts.write_json(charts.ROOT / 'data/information-audit/2021/taiwan-chart-gap.json',
        {'date': '2021-04-06', 'imported': len(imported), 'tickers': imported,
         'alternate_curves_retained': len(archived), 'alternate_tickers': archived,
         'method': 'Complete coherent TradingView curve; original observations retained as prior snapshots'})
    print('Taiwan coherent histories imported:', len(imported))


if __name__ == '__main__':
    main()
