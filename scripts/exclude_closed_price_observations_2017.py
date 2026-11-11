"""Keep exchange-closed provider values as provenance, outside regular charts."""
from datetime import datetime, timezone
import json

import stock_chart_history as charts


def main():
    config = json.loads((charts.ROOT / 'data/market-closures/2017.json').read_bytes())
    closed = {row['market']: set(row['dates']) for row in config['markets']}
    markets = {row['ticker']: row['market'] for row in charts.roster()}
    charts.DATABASE = charts.ROOT / 'data/tmp_2017_history/history.sqlite'
    db = charts.database()
    audit_path = charts.ROOT / 'data/information-audit/2017/excluded-closed-price-observations.json'
    prior = json.loads(audit_path.read_bytes())['listings'] if audit_path.exists() else []
    changed = {row['ticker']: row for row in prior}
    updated = 0
    for ticker, raw in db.execute('SELECT ticker,value FROM history').fetchall():
        value = json.loads(raw)
        excluded = [point for point in value['prices'] if point[0] in closed.get(markets.get(ticker), set())]
        if not excluded:
            continue
        snapshot = {key: item for key, item in value.items() if key != 'prior_snapshots'}
        snapshot.update(complete_history=False,
            preservation_reason='Provider values dated on officially closed exchange days retained as provenance, excluded from regular-session chart')
        value['prior_snapshots'] = [*value.get('prior_snapshots', []), snapshot]
        excluded_days = {point[0] for point in excluded}
        value['prices'] = [point for point in value['prices'] if point[0] not in excluded_days]
        value['excluded_2017_closed_dates'] = sorted(excluded_days)
        db.execute('UPDATE history SET value=? WHERE ticker=?', (json.dumps(value, ensure_ascii=False, separators=(',',':'), allow_nan=False), ticker))
        previous_days = changed.get(ticker, {}).get('excluded_dates', [])
        changed[ticker] = {'ticker': ticker, 'market': markets[ticker], 'excluded_dates': sorted(excluded_days | set(previous_days)), 'preserved_original_curve': True}
        updated += 1
    db.commit()
    charts.export_packs(db)
    db.close()
    charts.write_json(audit_path,
        {'checked_at': datetime.now(timezone.utc).isoformat(), 'listings': list(changed.values()),
         'excluded_points': sum(len(row['excluded_dates']) for row in changed.values())})
    print(f'Retained original curves separately and excluded closed-session values for {updated} additional listings')


if __name__ == '__main__':
    main()
