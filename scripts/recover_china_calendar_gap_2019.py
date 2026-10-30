"""Recover a confirmed China session missing across Yahoo's daily histories.

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
from backfill_yahoo_calendars import scan_universe, archive_ticker, request_yahoo, parse_bars
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
    universe_path = SOURCE_DIR.parent / f'tmp_{day.year}/china-gap-universe.json'
    if universe_path.exists():
        universe = json.loads(universe_path.read_bytes())
    else:
        universe = {'rows': scan_universe('china'), 'fetched_at': datetime.now(timezone.utc).isoformat()}
        atomic_json(universe_path, universe)
    rows = universe['rows']
    histories, failures = {}, {}

    def fetch(row):
        payload = cached_chart(row, '1D', 2800, cache_dir=cache, timeout=25, required_end=day)
        bars = chart_bars(payload, row)
        if not bars or len(bars) == 2800 and bars[0].day > day - timedelta(weeks=52):
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
                atomic_json(audit / 'china-gap-progress.json', {'date': str(day), 'total': len(rows),
                    'checked': done, 'failures': failures})
                print(f'china gap daily {done}/{len(rows)} verified={len(histories)}', flush=True)
    members = {symbol: (row, bars, payload) for symbol, (row, bars, payload) in histories.items()
               if any(bar.day == day for bar in bars)}
    counts = Counter(row['exchange'] for row, bars, payload in members.values())
    for exchange in ['SSE', 'SZSE']:
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
                'description': f"{row['description']} · {industry}", 'currency': row['currency'].upper(), 'source_symbol': symbol,
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
        'split_adjusted': True, 'session': 'regular', 'recovery_reason': f'Yahoo omits the confirmed trading session {day}',
        'calendar_reference': 'https://www.sse.com.cn/disclosure/announcement/general/c/c_20190418_4771364.shtml'}
    summary = '공식 거래일이지만 Yahoo 일봉에 누락된 날짜를 동일 거래소 TradingView 실제 일봉·월봉으로 복원했습니다. 현재 확인 가능한 종목군 기준입니다.'
    if failures or monthly_errors:
        summary = '부분 복원: 원본 미지원 상장은 제외했습니다. ' + summary
    report = {'schema_version': 1, 'market': 'china', 'date': str(day), 'summary': summary,
        'sources': [{'label': 'TradingView same-exchange daily and monthly histories', 'url': 'https://www.tradingview.com/'},
                    {'label': 'SSE official revised 2019 holiday schedule', 'url': meta['calendar_reference']}],
        'entries': sorted(entries, key=lambda r:(r['exchange'],r['ticker'])), 'source_metadata': meta, 'collected_at': now}
    markets = {r['id']:r for r in load_markets(SOURCE_DIR)}
    path = SOURCE_DIR / 'reports/china' / f'{day}.json'
    validate_report(report, path, SOURCE_DIR/'reports', markets)
    assert not path.exists(), path
    # B shares keep their actual USD/HKD quote units. Compare turnover only
    # after converting every listing with an observed rate for this exact day.
    currencies = {row['currency'].upper() for row, _, _ in members.values()}
    usd_rates = {'USD': 1.0}
    fx_sources = {}
    for currency in sorted(currencies | {'CNY'}):
        if currency == 'USD':
            continue
        fx_symbol = f'{currency}USD=X'
        payload = request_yahoo(fx_symbol, period1=day, period2=day+timedelta(days=3), range_name=None,
                                interval='1d', timeout=30, cache_dir=SOURCE_DIR.parent/'tmp_calendar_history')
        source = payload['chart']['result'][0]
        assert source['meta']['symbol'] == fx_symbol and source['meta']['currency'] == 'USD'
        observed = [bar.close for bar in parse_bars(payload, fx_symbol, source['meta']['exchangeTimezoneName']) if bar.day == day]
        assert len(observed) == 1 and observed[0] > 0, (currency, day, 'Missing exact-date FX')
        usd_rates[currency] = observed[0]
        fx_sources[currency] = {'symbol': fx_symbol, 'date': str(day), 'usd_per_currency': observed[0],
                                'source_url': f'https://finance.yahoo.com/quote/{fx_symbol}/history/'}
    cny_rates = {currency: usd_rates[currency]/usd_rates['CNY'] for currency in currencies}
    ranked = []
    for symbol, (row, bars, payload) in members.items():
        bar = next(bar for bar in bars if bar.day == day)
        if bar.volume <= 0 or bar.close <= 0:
            continue
        previous = next((b for b in reversed(bars) if b.day < day), None)
        ranked.append((bar.close*bar.volume*cny_rates[row['currency'].upper()], symbol, row, bar, previous))
    ranked.sort(key=lambda r:(-r[0],r[1])); turnover = []
    for rank, (amount, symbol, row, bar, previous) in enumerate(ranked[:30], 1):
        turnover.append({'rank': rank, 'ticker': archive_ticker(row), 'name': row['description'], 'exchange': row['exchange'],
            'price': bar.close, 'change_pct': (bar.close/previous.close-1)*100 if previous else None,
            'turnover': amount, 'currency': row['currency'].upper(), 'turnover_currency': 'CNY', 'market_cap': None, 'sector': row.get('sector') or '미분류',
            'industry': row.get('industry') or '업종 정보 미확인', 'source_symbol': symbol,
            'turnover_verification': {'date': str(day), 'session_close': bar.close, 'session_volume': bar.volume,
                                      'cny_per_price_currency': cny_rates[row['currency'].upper()], 'fx_date': str(day)}})
    assert len(turnover) == 30
    target = SOURCE_DIR.parent / 'turnover'
    monetary = {'schema_version': 1, 'market': 'china', 'date': str(day),
        'summary': summary + ' 종가×거래량을 동일 날짜의 원본 환율로 CNY 환산한 추정 거래대금 상위 30개입니다.', 'sources': report['sources'],
        'entries': turnover, 'source_metadata': {**meta, 'ranking': 'split-adjusted close × volume × dated CNY exchange rate descending',
                                                'turnover_currency': 'CNY', 'fx_date': str(day), 'historical_fx': fx_sources}}
    tpath = monthly_report_path(target/'reports', 'china', day)
    validate_turnover(monetary, tpath, target/'reports', {r['id']:r for r in load_markets(target)})
    assert not tpath.exists(), tpath
    atomic_json(audit / f'china-gap-recovery-{day}.json', {'date':str(day), 'metadata':meta,
        'histories':{symbol:{'sha256':hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest(),
                             'source_symbol':symbol} for symbol,(_,_,payload) in members.items()}})
    atomic_json(path, report); atomic_json(tpath, monetary)
    print(f'china {day}: recovered {len(entries)} new highs and 30 turnover entries from {len(members)} observed listings', flush=True)


if __name__ == '__main__':
    main()
