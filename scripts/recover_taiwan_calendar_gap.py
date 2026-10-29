"""Recover a confirmed Taiwan session missing across Yahoo's daily histories.

Uses complete same-listing TradingView daily/monthly observations. Does not
interpolate the missing session or splice differently adjusted providers.
"""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
import hashlib
import json

from archive_paths import monthly_report_path
from backfill_european_new_highs import cached_chart, chart_bars, candidates, classify_high
from backfill_yahoo_calendars import scan_universe, archive_ticker
from generate_new_high_data import SOURCE_DIR, load_markets, validate_report
from generate_turnover_data import validate_report as validate_turnover
from quote_sources.tradingview_chart import ChartHistoryError
from refresh_new_highs import atomic_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--date', required=True, type=date.fromisoformat)
    args = parser.parse_args()
    day = args.date
    cache = SOURCE_DIR.parent / 'tmp_tradingview_chart'
    audit = SOURCE_DIR.parent / f'information-audit/{day.year}'
    universe_path = SOURCE_DIR.parent / f'tmp_{day.year}/taiwan-gap-universe.json'
    if universe_path.exists():
        universe = json.loads(universe_path.read_bytes())
    else:
        universe = {'rows': scan_universe('taiwan'), 'fetched_at': datetime.now(timezone.utc).isoformat()}
        atomic_json(universe_path, universe)
    rows = universe['rows']
    histories, failures = {}, {}

    def fetch(row):
        payload = cached_chart(row, '1D', 2000, cache_dir=cache, timeout=25, required_end=day)
        bars = chart_bars(payload, row)
        if not bars or len(bars) == 2000 and bars[0].day > day - timedelta(weeks=52):
            raise ChartHistoryError('Insufficient daily lookback')
        return row, bars, payload

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(fetch, row): row for row in rows}
        for done, future in enumerate(as_completed(futures), 1):
            row = futures[future]
            try:
                histories[row['symbol']] = future.result()
            except ChartHistoryError as exc:
                failures[row['symbol']] = str(exc)
            if done % 100 == 0 or done == len(rows):
                atomic_json(audit / 'taiwan-gap-progress.json', {'date': str(day), 'total': len(rows),
                    'checked': done, 'failures': failures})
                print(f'taiwan gap daily {done}/{len(rows)} verified={len(histories)}', flush=True)
    members = {symbol: (row, bars, payload) for symbol, (row, bars, payload) in histories.items()
               if any(bar.day == day for bar in bars)}
    counts = Counter(row['exchange'] for row, bars, payload in members.values())
    for exchange in ['TWSE', 'TPEX']:
        eligible = sum(row['exchange'] == exchange and bars[0].day <= day for row, bars, _ in histories.values())
        assert eligible > 400 and counts[exchange] >= eligible * .9, (exchange, counts, eligible)
    evidence = {symbol: result[day] for symbol, (_, bars, _) in members.items()
                if day in (result := candidates(bars, {day}))}
    entries, monthly_errors = [], {}

    def classify(symbol):
        row, bars, _ = members[symbol]
        monthly = cached_chart(row, '1M', 1500, cache_dir=cache, timeout=25,
                               required_end=day.replace(day=1)-timedelta(days=1))
        months = chart_bars(monthly, row)
        kind, level = classify_high(bars, months, day, day)
        return symbol, kind, level

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(classify, symbol): symbol for symbol in evidence}
        for future in as_completed(futures):
            symbol = futures[future]
            try:
                _, high_type, level = future.result()
            except ChartHistoryError as exc:
                monthly_errors[symbol] = str(exc)
                continue
            row, bars, payload = members[symbol]
            check = evidence[symbol]; bar, previous = check['bar'], check['previous']
            sector, industry = row.get('sector') or '미분류', row.get('industry') or '업종 정보 미확인'
            entries.append({'ticker': archive_ticker(row), 'name': row['description'], 'exchange': row['exchange'],
                'category': sector, 'high_type': high_type, 'reason': f'업종: {sector} · {industry}',
                'description': f"{row['description']} · {industry}", 'currency': 'TWD', 'source_symbol': symbol,
                'change_pct': (bar.close/previous.close-1)*100 if previous else None,
                'session_open': bar.open, 'session_close': bar.close, 'session_volume': bar.volume,
                'high_verification': {'source': 'TradingView same-listing daily and complete monthly history',
                    'source_url': f"https://www.tradingview.com/symbols/{row['exchange']}-{row['name']}/",
                    'date': str(day), 'daily_high': bar.high, 'prior_all_time_or_current_month_high': level}})
    now = datetime.now(timezone.utc).isoformat()
    meta = {'provider': 'TradingView verified same-listing daily/monthly histories', 'fetched_at': now,
        'universe_fetched_at': universe['fetched_at'], 'scanned_symbols': len(rows), 'history_symbols': len(histories),
        'session_symbols': len(members), 'session_symbols_by_exchange': dict(counts), 'unresolved_listings': failures,
        'unresolved_monthly_listings': monthly_errors, 'coverage_status': 'partial' if failures or monthly_errors else 'verified',
        'split_adjusted': True, 'session': 'regular', 'recovery_reason': 'Yahoo omits the confirmed trading session 2021-04-06',
        'calendar_reference': 'https://www.twse.com.tw/downloads/zh/about/company/factbook/2022/3.01.html'}
    summary = '공식 거래일이지만 Yahoo 일봉에 누락된 날짜를 동일 거래소 TradingView 실제 일봉·월봉으로 복원했습니다. 현재 확인 가능한 종목군 기준입니다.'
    if failures or monthly_errors:
        summary = '부분 복원: 원본 미지원 상장은 제외했습니다. ' + summary
    report = {'schema_version': 1, 'market': 'taiwan', 'date': str(day), 'summary': summary,
        'sources': [{'label': 'TradingView same-exchange daily and monthly histories', 'url': 'https://www.tradingview.com/'},
                    {'label': 'TWSE official 2021 trading-day totals', 'url': meta['calendar_reference']}],
        'entries': sorted(entries, key=lambda r:(r['exchange'],r['ticker'])), 'source_metadata': meta, 'collected_at': now}
    markets = {r['id']:r for r in load_markets(SOURCE_DIR)}
    path = SOURCE_DIR / 'reports/taiwan' / f'{day}.json'
    validate_report(report, path, SOURCE_DIR/'reports', markets)
    assert not path.exists(), path
    ranked = []
    for symbol, (row, bars, payload) in members.items():
        bar = next(bar for bar in bars if bar.day == day)
        if bar.volume <= 0 or bar.close <= 0:
            continue
        previous = next((b for b in reversed(bars) if b.day < day), None)
        ranked.append((bar.close*bar.volume, symbol, row, bar, previous))
    ranked.sort(key=lambda r:(-r[0],r[1])); turnover = []
    for rank, (amount, symbol, row, bar, previous) in enumerate(ranked[:30], 1):
        turnover.append({'rank': rank, 'ticker': archive_ticker(row), 'name': row['description'], 'exchange': row['exchange'],
            'price': bar.close, 'change_pct': (bar.close/previous.close-1)*100 if previous else None,
            'turnover': amount, 'currency': 'TWD', 'market_cap': None, 'sector': row.get('sector') or '미분류',
            'industry': row.get('industry') or '업종 정보 미확인', 'source_symbol': symbol})
    assert len(turnover) == 30
    target = SOURCE_DIR.parent / 'turnover'
    monetary = {'schema_version': 1, 'market': 'taiwan', 'date': str(day),
        'summary': summary + ' 종가×거래량 추정 거래대금 상위 30개입니다.', 'sources': report['sources'],
        'entries': turnover, 'source_metadata': {**meta, 'ranking': 'split-adjusted close × volume descending'}}
    tpath = monthly_report_path(target/'reports', 'taiwan', day)
    validate_turnover(monetary, tpath, target/'reports', {r['id']:r for r in load_markets(target)})
    assert not tpath.exists(), tpath
    atomic_json(audit / 'taiwan-gap-recovery.json', {'date':str(day), 'metadata':meta,
        'histories':{symbol:{'sha256':hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest(),
                             'source_symbol':symbol} for symbol,(_,_,payload) in members.items()}})
    atomic_json(path, report); atomic_json(tpath, monetary)
    print(f'taiwan {day}: recovered {len(entries)} new highs and 30 turnover entries from {len(members)} observed listings', flush=True)


if __name__ == '__main__':
    main()
