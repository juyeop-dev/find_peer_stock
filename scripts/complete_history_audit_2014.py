"""Record retained listing coverage and explicitly recheck missing original curves."""
from concurrent.futures import ThreadPoolExecutor
import argparse
from datetime import datetime, timezone
import json
import sys
import time

import stock_chart_history as charts
import stock_information as info
from refresh_stock_information_history import fallback


def transient_error(error):
    message = str(error or '').lower()
    return any(marker in message for marker in (
        'connection closed before series completion', 'connectionabortederror',
        'connectionreseterror', 'timeouterror', 'timed out', 'urlerror',
        'winerror 10053', 'winerror 10054', 'temporary failure',
        'rate limit', 'access limited', 'http error 403', 'http error 429',
        'install scripts/requirements-chart-history.txt',
    ))


def fetch_original(row, mapped_symbol):
    for attempt in range(1, 4):
        try:
            return fallback(row, mapped_symbol), attempt, None
        except Exception as error:
            if getattr(error, 'code', None) in {403, 429}:
                raise
            if not transient_error(error) or attempt == 3:
                return None, attempt, f'{type(error).__name__}: {error}'
            time.sleep(attempt)


def main():
    sys.path.insert(0, str(charts.ROOT / 'data/tmp_info_update/deps'))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-export", action="store_true")
    parser.add_argument("--export", action="store_true", help="Export only when this audit is the final writer")
    args = parser.parse_args()
    state = charts.ROOT / 'data/tmp_2014_history'
    charts.DATABASE = state / 'history.sqlite'
    db, history = info.open_database(state), charts.database()
    rows = charts.roster()
    checkpoints = {ticker: json.loads(raw) for ticker, raw in db.execute('SELECT ticker,value FROM history_2014_updates')}
    completed = set(checkpoints)
    mappings = {value['ticker']: value['symbol'] for path in (state / 'mappings').glob('*.json')
                if (value := json.loads(path.read_bytes())).get('symbol')}
    missing = []
    for row in rows:
        prior = checkpoints.get(row['ticker'], {})
        if not prior.get('updated') and transient_error(prior.get('error')):
            missing.append(row)
            continue
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
        db.execute('INSERT OR REPLACE INTO history_2014_updates VALUES (?,?)', (row['ticker'], json.dumps(result)))
    db.commit()
    unresolved_transient = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(fetch_original, row, mappings.get(row['ticker'])) for row in missing]
        for row, future in zip(missing, futures):
            result = {'ticker': row['ticker'], 'order': row['order'], 'updated': False, 'queried_at': datetime.now(timezone.utc).isoformat()}
            try:
                value, attempts, error = future.result()
                result.update(attempts=attempts, error=error)
                if value is not None:
                    old = history.execute('SELECT value FROM history WHERE ticker=?', (row['ticker'],)).fetchone()
                    if old and not value.get('first_trade_date'):
                        value['first_trade_date'] = json.loads(old[0]).get('first_trade_date')
                    charts.save_candidate(history, value, historical_start='2014-01-01')
                    history.commit()
                    result.update(updated=True, error=None)
            except Exception as error:
                if getattr(error, 'code', None) in {403,429}:
                    raise
                result['error'] = f'{type(error).__name__}: {error}'
            if not result['updated'] and transient_error(result.get('error')):
                unresolved_transient.append(row['ticker'])
            db.execute('INSERT OR REPLACE INTO history_2014_updates VALUES (?,?)', (row['ticker'], json.dumps(result)))
            db.commit()
            print(f"Checked missing original {row['ticker']}: available={result['updated']}", flush=True)
    info.checkpoint(db, rows, history)
    if args.export:
        charts.export_packs(history)
    history.close()
    db.close()
    if unresolved_transient:
        raise RuntimeError(f'Transient source errors remain after retries; not classified as unavailable: {unresolved_transient}')


if __name__ == '__main__':
    main()
