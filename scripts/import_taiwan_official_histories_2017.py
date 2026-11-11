"""Keep complete same-listing curves with independently verified Saturday quotes."""
from pathlib import Path
import hashlib
import json

import stock_chart_history as charts
from backfill_yahoo_calendars import archive_ticker
from import_recovered_histories_2019 import retain_curve


def main():
    charts.DATABASE = charts.ROOT / 'data/tmp_2017_history/history.sqlite'
    db = charts.database()
    universe = json.loads((charts.ROOT / 'data/tmp_2017/taiwan-gap-universe.json').read_bytes())
    proofs = {}
    for day in ['2017-02-18', '2017-06-03', '2017-09-30']:
        value = json.loads((charts.ROOT / f'data/information-audit/2017/taiwan-official-recovery-{day}.json').read_bytes())
        for symbol, proof in value['members'].items():
            proofs.setdefault(symbol, {})[day] = proof
    imported, alternate = [], []
    for row in universe['rows']:
        symbol = row['symbol']
        if symbol not in proofs:
            continue
        path = charts.ROOT / 'data/tmp_tradingview_chart/1D' / (hashlib.sha256(f'{symbol}:1D:3200'.encode()).hexdigest()+'.json')
        raw = path.read_bytes()
        payload = json.loads(raw)
        if any(proof['chart_sha256'] != hashlib.sha256(raw).hexdigest() for proof in proofs[symbol].values()):
            raise ValueError('Underlying verified price basis changed')
        ticker = archive_ticker(row)
        stored = db.execute('SELECT value FROM history WHERE ticker=?', (ticker,)).fetchone()
        if not stored:
            continue
        previous = json.loads(stored[0])
        fresh = charts.parse_tradingview(payload, symbol)
        prices = {point[0]: point for point in fresh['prices'] if point[0] >= '2016-12-20'}
        for day, proof in proofs[symbol].items():
            if day in prices:
                raise ValueError('Official Saturday would replace an existing observation')
            close = proof['original_bar']['close'] * proof['factor']
            prices[day] = [day, close, close]
        fresh.update(ticker=ticker, source_symbol=symbol, fetched_at=payload['fetched_at'],
            source=fresh['source']+' / official TWSE-TPEx Saturday quotes with independently verified split basis',
            first_trade_date=previous.get('first_trade_date'), prices=[prices[day] for day in sorted(prices)],
            historical_2017_extension={'mode': 'verified_same_listing_split_basis', 'official_saturday_quotes': proofs[symbol],
                'source_sha256': hashlib.sha256(raw).hexdigest(), 'cache': path.relative_to(charts.ROOT).as_posix()})
        result, older = retain_curve(previous, fresh)
        db.execute('UPDATE history SET value=? WHERE ticker=?', (json.dumps(result, ensure_ascii=False, separators=(',',':'), allow_nan=False), ticker))
        (alternate if older else imported).append(ticker)
    db.commit()
    charts.export_packs(db)
    db.close()
    charts.write_json(charts.ROOT / 'data/information-audit/2017/taiwan-official-price-curves.json',
        {'primary_tickers': imported, 'older_alternate_tickers': alternate,
         'primary_count': len(imported), 'older_alternate_count': len(alternate)})
    print(f'Imported {len(imported)} verified Saturday price curves; retained {len(alternate)} older alternatives')


if __name__ == '__main__':
    main()
