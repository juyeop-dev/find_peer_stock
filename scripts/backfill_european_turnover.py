"""Restore dated USD-normalized turnover from a complete, verified European chart cache."""
import argparse
import hashlib
import json
import math
import sys
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from archive_paths import monthly_report_path
from backfill_european_new_highs import chart_bars, verify_series_end, validate_session_coverage
from backfill_yahoo_calendars import request_yahoo, published_exchange, parse_bars
from generate_turnover_data import SOURCE_DIR, load_markets, validate_report
from refresh_new_highs import atomic_json
from quote_sources.tradingview_chart import ChartHistoryError

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--start', required=True, type=date.fromisoformat)
parser.add_argument('--end', required=True, type=date.fromisoformat)
parser.add_argument('--daily-bars', type=int, default=1000)
parser.add_argument('--partial-history', action='store_true', help='Explicitly label partial historical observations; retain strict coverage checks by default.')
args = parser.parse_args()
START, END = args.start, args.end
assert START.year == END.year and END >= START
review_path = f'data/turnover/reviews/europe/{START}_to_{END}.json'
CACHE = ROOT / 'data/tmp_tradingview_chart'
universe_path = CACHE / 'universe.json'
universe = json.loads(universe_path.read_text(encoding='utf-8'))
reference = json.loads((ROOT / f'data/new-highs/reports/europe/{START}.json').read_text(encoding='utf-8'))
reference_meta = reference['source_metadata']
rows = universe['rows']
assert len(rows) == reference_meta['scanned_symbols']
assert not universe['excluded'], 'This recovery requires the complete verified universe'
excluded = {item['symbol']: item for item in reference_meta['non_stock_exclusions']}
assert all(item['type'] != 'stock' for item in excluded.values())
histories = {}
manifest = {}
for row in rows:
    symbol = row['symbol']
    if symbol in excluded:
        continue
    digest = hashlib.sha256(f'{symbol}:1D:{args.daily_bars}'.encode()).hexdigest()
    path = CACHE / '1D' / f'{digest}.json'
    raw = path.read_bytes()
    payload = json.loads(raw)
    bars = chart_bars(payload, row)
    assert bars, symbol
    verify_series_end(row, bars, END)
    assert all(a.day < b.day for a, b in zip(bars, bars[1:])), symbol
    for bar in bars:
        assert math.isfinite(bar.close) and bar.close >= 0, symbol
        assert math.isfinite(bar.volume) and bar.volume >= 0, symbol
        if START <= bar.day <= END and bar.volume > 0:
            assert bar.close > 0, symbol
    histories[symbol] = (row, bars)
    manifest[symbol] = {'sha256': hashlib.sha256(raw).hexdigest(), 'fetched_at': payload['fetched_at']}
assert len(histories) == reference_meta['history_required_symbols'] == reference_meta['history_symbols']
print(f'europe: verified all {len(histories)} cached stock histories', flush=True)

sessions = [START + timedelta(days=i) for i in range((END - START).days + 1)
            if (START + timedelta(days=i)).weekday() < 5]
closed_market = next(set(item['dates']) for item in json.loads((ROOT / f'data/market-closures/{START.year}.json').read_text(encoding='utf-8'))['markets'] if item['market'] == 'europe')
sessions = [day for day in sessions if str(day) not in closed_market]
closures = json.loads((ROOT / 'data/new-highs/europe-exchange-closures.json').read_text(encoding='utf-8'))['closures']
currencies = {row['currency'].upper() for row, _bars in histories.values()}
fx_currencies = {('GBP' if c == 'GBX' else c) for c in currencies} - {'USD'}
fx = {'USD': {session: 1.0 for session in sessions}}
fx_sources = {}
for currency in sorted(fx_currencies):
    symbol = f'{currency}USD=X'
    payload = request_yahoo(symbol, period1=START, period2=END + timedelta(days=2),
                            range_name=None, interval='1d', timeout=30,
                            cache_dir=ROOT / 'data/tmp_calendar_history')
    result = payload['chart']['result'][0]
    assert result['meta']['symbol'] == symbol
    assert result['meta']['currency'] == 'USD'
    bars = parse_bars(payload, symbol, result['meta']['exchangeTimezoneName'])
    fx[currency] = {bar.day: bar.close for bar in bars if bar.day in sessions}
    assert all(session in fx[currency] for session in sessions), (currency, 'missing dated FX rate')
    fx_sources[currency] = {'symbol': symbol, 'url': f'https://finance.yahoo.com/quote/{symbol}/history/',
                            'usd_per_currency_by_date': {str(day): value for day, value in sorted(fx[currency].items())}}
    print(f'europe: {currency}/USD verified for {len(sessions)} sessions', flush=True)

markets = {item['id']: item for item in load_markets(SOURCE_DIR)}
reports, checks = {}, {}
fetched_at = datetime.now(timezone.utc).isoformat()
for session in sessions:
    closed = {item['exchange'] for item in closures if item['date'] == str(session)}
    candidates = []
    by_exchange = Counter()
    for symbol, (row, bars) in histories.items():
        current = next((bar for bar in bars if bar.day == session), None)
        if current is None:
            continue
        by_exchange[row['exchange']] += 1
        # Closed-exchange chart points may be OTC/off-book reporting. They must
        # not enter an on-exchange calendar ranking.
        if row['exchange'] in closed or current.volume <= 0:
            continue
        currency = row['currency'].upper()
        usd_rate = fx['GBP' if currency == 'GBX' else currency][session]
        if currency == 'GBX':
            usd_rate /= 100
        turnover = current.close * current.volume * usd_rate
        assert math.isfinite(turnover) and turnover > 0
        previous = next((bar for bar in reversed(bars) if bar.day < session and bar.close > 0), None)
        candidates.append((turnover, symbol, row, current, previous, usd_rate))
    coverage_warning = None
    try:
        validate_session_coverage(session, dict(by_exchange), [row for row, _bars in histories.values()], closed)
    except ChartHistoryError as exc:
        if not args.partial_history:
            raise
        coverage_warning = str(exc)
    ranked = sorted(candidates, key=lambda item: (-item[0], item[1]))[:30]
    assert len(ranked) == 30
    entries = []
    for rank, (turnover, symbol, row, bar, previous, usd_rate) in enumerate(ranked, 1):
        entries.append({
            'rank': rank, 'ticker': symbol, 'source_symbol': symbol,
            'name': row['description'], 'exchange': published_exchange(row['exchange']),
            'price': bar.close, 'currency': row['currency'].upper(),
            'change_pct': (bar.close / previous.close - 1) * 100 if previous else None,
            'turnover': turnover, 'turnover_currency': 'USD', 'market_cap': None,
            'sector': row.get('sector') or '미분류', 'industry': row.get('industry') or '업종 정보 미확인',
            'turnover_verification': {'date': str(session), 'session_close': bar.close,
                'session_volume': bar.volume, 'usd_per_price_currency': usd_rate,
                'fx_date': str(session), 'chart_source_id': row['exchange'],
                'source_url': f'https://www.tradingview.com/symbols/{row["exchange"]}-{row["name"]}/'},
        })
    rates = {currency: (fx['GBP'][session] / 100 if currency == 'GBX' else fx[currency][session])
             for currency in sorted(currencies)}
    reports[session] = {
        'schema_version': 1, 'market': 'europe', 'date': str(session),
        'summary': ('부분 복원: 당시 일봉이 확인된 종목 안에서의 순위이며 시장 전체 순위와 다를 수 있습니다. ' + ' · '.join(f"{exchange} {by_exchange[exchange]}/{sum(row['exchange'] == exchange for row, _bars in histories.values())}종목 확인" for exchange in by_exchange) + '. ' if args.partial_history else '') + 'TradingView 동일 거래소 과거 일봉의 종가×거래량을 당일 환율로 미달러 환산한 추정 거래대금 상위 30개 종목입니다. GBX는 GBP의 1/100로 환산하며 휴장 거래소는 제외합니다.',
        'sources': [{'label': 'TradingView same-exchange daily charts', 'url': 'https://www.tradingview.com/'},
                    {'label': 'Yahoo Finance dated currency/USD exchange rates', 'url': 'https://finance.yahoo.com/currencies/'}],
        'entries': entries,
        'source_metadata': {
            'provider': 'TradingView public daily chart history',
            'universe_provider': 'TradingView public scanner',
            'fetched_at': fetched_at, 'universe_fetched_at': universe['fetched_at'],
            'universe': reference_meta['universe'], 'scanned_symbols': len(rows),
            'history_symbols': len(histories), 'unresolved_symbols': 0, 'coverage_ratio': sum(by_exchange.values()) / len(histories),
            'coverage_status': 'partial' if args.partial_history else 'verified', 'coverage_warning': coverage_warning,
            'non_stock_exclusions': list(excluded.values()),
            'session_symbols': sum(by_exchange.values()), 'session_symbols_by_exchange': dict(by_exchange),
            'scheduled_closed_exchanges': sorted(closed),
            'split_adjusted': True, 'session': 'regular', 'pagination_complete': True,
            'ranking': 'split-adjusted close × volume × dated currency/USD rate descending',
            'turnover_currency': 'USD', 'turnover_is_estimate': True,
            'fx_provider': 'Yahoo Finance daily chart close', 'fx_date': str(session),
            'usd_per_price_currency': rates, 'gbx_per_gbp': 100,
            'review_path': review_path,
        },
    }
    path = monthly_report_path(SOURCE_DIR / 'reports', 'europe', session)
    validate_report(reports[session], path, SOURCE_DIR / 'reports', markets)
    checks[str(session)] = {'count': len(entries), 'session_symbols_by_exchange': dict(by_exchange),
                            'scheduled_closed_exchanges': sorted(closed)}

# Publish only after every date, listing identity, coverage check and FX series passes.
atomic_json(ROOT / review_path, {
    'schema_version': 1, 'market': 'europe', 'start': str(START), 'end': str(END), 'reviewed_at': fetched_at,
    'universe_fetched_at': universe['fetched_at'],
    'universe_sha256': hashlib.sha256(universe_path.read_bytes()).hexdigest(),
    'scanned_symbols': len(rows), 'history_symbols': len(histories),
    'non_stock_exclusions': list(excluded.values()), 'historical_fx': fx_sources,
    'checks': checks, 'chart_manifest': manifest,
})
for session, report in reports.items():
    path = monthly_report_path(SOURCE_DIR / 'reports', 'europe', session)
    if not path.exists():
        atomic_json(path, report)
        print(f'europe {session}: turnover=30', flush=True)
