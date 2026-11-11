"""Record retained listing coverage and explicitly recheck missing original curves."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json

import stock_chart_history as charts
import stock_information as info
from refresh_stock_information_history import fallback


def main():
    state = charts.ROOT / 'data/tmp_2017_history'
    charts.DATABASE = state / 'history.sqlite'
    db, history = info.open_database(state), charts.database()
    rows = charts.roster()
    completed = {ticker for ticker, in db.execute('SELECT ticker FROM history_2017_updates')}
    missing = []
    for row in rows:
        if row['ticker'] in completed:
            continue
        stored = history.execute('SELECT value FROM history WHERE ticker=?', (row['ticker'],)).fetchone()
        value = json.loads(stored[0]) if stored else {}
        if len(value.get('prices', [])) < 2:
            missing.append(row)
            continue
        result = {'ticker': row['ticker'], 'order': row['order'], 'updated': True, 'error': None,
                  'cache_status': 'retained_verified_listing_curve', 'queried_at': datetime.now(timezone.utc).isoformat(),
                  'first_price': value['prices'][0][0], 'first_trade_date': value.get('first_trade_date')}
        db.execute('INSERT OR REPLACE INTO history_2017_updates VALUES (?,?)', (row['ticker'], json.dumps(result)))
    db.commit()
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(fallback, row) for row in missing]
        for row, future in zip(missing, futures):
            result = {'ticker': row['ticker'], 'order': row['order'], 'updated': False, 'queried_at': datetime.now(timezone.utc).isoformat()}
            try:
                value = future.result()
                charts.save_candidate(history, value, historical_start='2017-01-01')
                history.commit()
                result.update(updated=True, error=None)
            except Exception as error:
                if getattr(error, 'code', None) in {403,429}:
                    raise
                result['error'] = f'{type(error).__name__}: {error}'
            db.execute('INSERT OR REPLACE INTO history_2017_updates VALUES (?,?)', (row['ticker'], json.dumps(result)))
            db.commit()
            print(f"Checked missing original {row['ticker']}: available={result['updated']}", flush=True)
    info.checkpoint(db, rows, history)
    charts.export_packs(history)
    history.close()
    db.close()


if __name__ == '__main__':
    main()
