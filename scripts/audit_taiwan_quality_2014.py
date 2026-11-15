"""Independently verify original Saturday quotes, adjacent returns and full curves."""
from datetime import date, timedelta
import hashlib
import json
import math
import sqlite3

from archive_paths import monthly_report_path
from backfill_european_new_highs import chart_bars
from backfill_yahoo_calendars import archive_ticker
from repair_taiwan_adjacent_2014 import ROOT, SATURDAY, SESSIONS, retained_curves
from stock_chart_history import write_json


def verify_original_curves(matching, expected, closed, symbol):
    complete_original_retained = False
    for curve in matching:
        assert curve['currency'] == 'TWD'
        observed = {point[0]: point for point in curve['prices']}
        assert len(observed) == len(curve['prices']), symbol
        omitted = set(expected) - set(observed)
        # Only explicitly recorded official closures may leave the regular
        # curve. A complete unchanged original must still exist independently.
        assert omitted <= closed & set(curve.get('excluded_2014_closed_dates', [])), (symbol, omitted)
        complete_original_retained |= not omitted
        extension = curve['historical_2014_extension']
        for day, point in observed.items():
            original = expected.get(day)
            if original is None:
                proof = extension['official_saturday_quotes'][day]
                assert proof['chart_sha256'] == extension['source_sha256'], (symbol, day)
                close = proof['original_bar']['close'] * proof['factor']
                original = [day, close, close]
            assert point == original, (symbol, day)
    assert complete_original_retained, (symbol, 'Complete provider original was not retained')


def main():
    recovery = json.loads((ROOT / 'data/information-audit/2014/taiwan-official-recovery-2014-12-27.json').read_bytes())
    adjacent = json.loads((ROOT / 'data/information-audit/2014/taiwan-adjacent-source.json').read_bytes())
    curves, errors, originals, sources = retained_curves()
    assert errors == adjacent['unresolved_listings']
    assert adjacent['original_sources'] == sources
    for source in sources:
        assert hashlib.sha256((ROOT / source['cache']).read_bytes()).hexdigest() == source['sha256']
    for symbol, record in adjacent['histories'].items():
        assert record['sha256'] == curves[symbol]['sha256'], symbol
    universe = json.loads((ROOT / 'data/tmp_2014/taiwan-gap-universe.json').read_bytes())['rows']
    config = json.loads((ROOT / 'data/market-closures/2014.json').read_bytes())
    closed = set(next(row['dates'] for row in config['markets'] if row['market'] == 'taiwan'))
    eligible = {row['symbol'] for row in universe if (quote := originals[row['exchange'], SATURDAY].get(row['name'])) and quote['bar'].volume > 0}
    assert len(eligible) == recovery['official_members']
    assert len(recovery['members']) >= len(eligible)*.9
    with sqlite3.connect(ROOT / 'data/tmp_2014_history/history.sqlite') as db:
        coherent = 0
        for row in universe:
            symbol = row['symbol']
            if symbol not in recovery['members']:
                continue
            proof = recovery['members'][symbol]
            value = json.loads(db.execute('SELECT value FROM history WHERE ticker=?', (archive_ticker(row),)).fetchone()[0])
            close = proof['original_bar']['close']*proof['factor']
            alternatives = [value, *value.get('prior_snapshots', [])]
            matching = [curve for curve in alternatives if curve.get('historical_2014_extension', {}).get('source_sha256') == proof['chart_sha256']]
            assert matching, symbol
            expected = {str(bar.day): [str(bar.day), bar.close, bar.close]
                        for bar in curves[symbol]['bars'] if str(bar.day) >= '2013-12-20'}
            assert expected['2014-12-27'] == ['2014-12-27', close, close], symbol
            verify_original_curves(matching, expected, closed, symbol)
            coherent += 1
    for session in [SATURDAY, SESSIONS[0]]:
        ranked = []
        for row in universe:
            quote = originals[row['exchange'], session].get(row['name'])
            if quote and quote['bar'].volume > 0:
                ranked.append((quote['amount'], row['symbol'], row, quote))
        ranked.sort(key=lambda item: (-item[0], item[1]))
        report = json.loads(monthly_report_path(ROOT / 'data/turnover/reports', 'taiwan', session).read_bytes())
        assert [(row['turnover'], row['source_symbol']) for row in report['entries']] == [(row[0], row[1]) for row in ranked[:30]]
        for entry, (_, symbol, row, quote) in zip(report['entries'], ranked[:30], strict=True):
            assert entry['price'] == quote['bar'].close and entry['currency'] == 'TWD'
            if session == SATURDAY:
                before = originals[row['exchange'], date(2014, 12, 26)].get(row['name'])
                expected = (quote['bar'].close/before['bar'].close-1)*100 if before else None
            else:
                member = curves.get(symbol)
                before = [bar for bar in member['bars'] if bar.day < session] if member else []
                today = next((bar for bar in member['bars'] if bar.day == session), None) if member else None
                expected = (today.close/before[-1].close-1)*100 if today and before else None
                assert entry['change_verification']['previous_date'] == (str(before[-1].day) if today and before else None)
            assert entry['change_pct'] == expected, symbol
    monthly_hashes = {}
    for session in SESSIONS:
        expected = set()
        for symbol, member in curves.items():
            bars = member['bars']
            index = next((index for index, bar in enumerate(bars) if bar.day == session), None)
            if index is None:
                continue
            today = bars[index]
            previous = bars[index-1] if index else None
            prior = [bar.high for bar in bars if session-timedelta(weeks=52) <= bar.day < session]
            if today.volume <= 0 or today.high < max([today.high, *prior])*(1-1e-10) or today.close < today.open or previous and today.close < previous.close:
                continue
            if symbol not in adjacent['monthly_errors']:
                expected.add(symbol)
        report = json.loads((ROOT / f'data/new-highs/reports/taiwan/{session}.json').read_bytes())
        assert {entry['source_symbol'] for entry in report['entries']} == expected, str(session)
        for entry in report['entries']:
            symbol = entry['source_symbol']
            bars = curves[symbol]['bars']
            index = next(index for index, bar in enumerate(bars) if bar.day == session)
            today, previous = bars[index], bars[index-1] if index else None
            expected_change = (today.close/previous.close-1)*100 if previous else None
            assert entry['change_pct'] == expected_change
            assert entry['session_close'] == today.close and entry['session_open'] == today.open and entry['session_volume'] == today.volume
            path = ROOT / 'data/tmp_tradingview_chart/1M' / (hashlib.sha256(f'{symbol}:1M:1500'.encode()).hexdigest()+'.json')
            months = chart_bars(json.loads(path.read_bytes()), curves[symbol]['row'])
            monthly_hashes[symbol] = hashlib.sha256(path.read_bytes()).hexdigest()
            level = max([0, *[bar.high for bar in months if bar.day < date(2014, 12, 1)], *[bar.high for bar in bars if date(2014, 12, 1) <= bar.day <= session]])
            assert entry['high_type'] == ('all_time' if today.high >= level*(1-1e-10) else '52_week')
            assert math.isclose(entry['high_verification']['prior_all_time_or_current_month_high'], level, rel_tol=1e-14)
    result = {'date': '2014-12-27', 'eligible_listings': len(eligible), 'verified_listings': len(recovery['members']),
        'coherent_curves': coherent, 'turnover_top30_verified': True, 'adjacent_returns_verified': True,
        'adjacent_highs_verified': [str(day) for day in SESSIONS], 'monthly_source_sha256': monthly_hashes,
        'scope': 'Current listed common-stock cohort; delisted and unverified listings explicitly excluded'}
    write_json(ROOT / 'data/information-audit/2014/taiwan-quality.json', result)
    print({key: value for key, value in result.items() if key != 'monthly_source_sha256'}, flush=True)


if __name__ == '__main__':
    main()
