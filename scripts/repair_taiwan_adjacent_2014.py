"""Include the official Saturday when checking subsequent daily highs and returns."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
import hashlib
import json

from archive_paths import monthly_report_path
from backfill_european_new_highs import chart_bars, candidates, classify_high, cached_chart
from backfill_yahoo_calendars import Bar, archive_ticker
from recover_taiwan_official_2014 import ROOT, original, verified_factor
from refresh_new_highs import atomic_json

SATURDAY = date(2014, 12, 27)
SESSIONS = [date(2014, 12, day) for day in [29, 30, 31]]
PROOF = ROOT / 'data/information-audit/2014/taiwan-adjacent-source.json'


def retained_curves():
    universe = json.loads((ROOT / 'data/tmp_2014/taiwan-gap-universe.json').read_bytes())
    recovery = json.loads((ROOT / 'data/information-audit/2014/taiwan-official-recovery-2014-12-27.json').read_bytes())
    quotes, sources = {}, []
    for exchange in ['TWSE', 'TPEX']:
        for day in [date(2014, 12, 26), SATURDAY, SESSIONS[0]]:
            quotes[exchange, day], source = original(exchange, day)
            sources.append(source)
    curves, errors = {}, {}
    for row in universe['rows']:
        symbol = row['symbol']
        path = ROOT / 'data/tmp_tradingview_chart/1D' / (hashlib.sha256(f'{symbol}:1D:3700'.encode()).hexdigest()+'.json')
        raw = path.read_bytes()
        payload = json.loads(raw)
        bars = chart_bars(payload, row)
        quote = quotes[row['exchange'], SATURDAY].get(row['name'])
        if quote and quote['bar'].volume > 0:
            proof = recovery['members'].get(symbol)
            if not proof:
                errors[symbol] = 'Official Saturday traded; compatible split basis not verified'
                continue
            assert proof['chart_sha256'] == hashlib.sha256(raw).hexdigest(), symbol
            before = quotes[row['exchange'], date(2014, 12, 26)][row['name']]['bar']
            after = quotes[row['exchange'], SESSIONS[0]][row['name']]['bar']
            factor = verified_factor(before, after, bars)
            assert factor == proof['factor'], symbol
            bar = quote['bar']
            assert not any(item.day == SATURDAY for item in bars), symbol
            bars.append(Bar(SATURDAY, bar.open*factor, bar.high*factor, bar.low*factor, bar.close*factor, bar.volume/factor))
            bars.sort(key=lambda item: item.day)
        curves[symbol] = {'row': row, 'bars': bars, 'sha256': hashlib.sha256(raw).hexdigest()}
    return curves, errors, quotes, sources


def main():
    if PROOF.exists():
        print('Preserved completed Taiwan Saturday-adjacent correction', flush=True)
        return
    curves, errors, quotes, sources = retained_curves()
    checks = {symbol: candidates(value['bars'], set(SESSIONS)) for symbol, value in curves.items()}
    cache = ROOT / 'data/tmp_tradingview_chart'
    needed = [symbol for symbol, values in checks.items() if values]
    def monthly(symbol):
        member = curves[symbol]
        payload = cached_chart(member['row'], '1M', 1500, cache_dir=cache, timeout=25, required_end=date(2014, 11, 30))
        return chart_bars(payload, member['row'])
    monthly_errors, months = {}, {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {symbol: pool.submit(monthly, symbol) for symbol in needed}
        for symbol, future in futures.items():
            try:
                months[symbol] = future.result()
            except Exception as error:
                if any(term in str(error).lower() for term in ['forbidden', 'unauthorized', 'rate limit', 'winerror 10013']):
                    raise
                monthly_errors[symbol] = str(error)
    backup = ROOT / 'data/tmp_2014/taiwan-adjacent-originals'
    backup.mkdir(parents=True, exist_ok=True)
    for session in SESSIONS:
        path = ROOT / f'data/new-highs/reports/taiwan/{session}.json'
        report = json.loads(path.read_bytes())
        target = backup / path.name
        if not target.exists():
            target.write_bytes(path.read_bytes())
        entries = []
        for symbol, values in checks.items():
            if session not in values or symbol not in months:
                continue
            member, check = curves[symbol], values[session]
            row, bar, previous = member['row'], check['bar'], check['previous']
            kind, level = classify_high(member['bars'], months[symbol], session, session)
            entries.append({'ticker': archive_ticker(row), 'name': row['description'], 'exchange': row['exchange'],
                'category': row.get('sector') or '미분류', 'high_type': kind,
                'reason': '공식 토요일 거래를 포함한 52주·전체기간 고점 대조', 'description': row['description'],
                'currency': 'TWD', 'source_symbol': symbol,
                'change_pct': (bar.close/previous.close-1)*100 if previous else None,
                'session_open': bar.open, 'session_close': bar.close, 'session_volume': bar.volume,
                'high_verification': {'source': 'Verified same-listing daily/monthly history including official Saturday',
                    'date': str(session), 'daily_high': bar.high, 'prior_all_time_or_current_month_high': level,
                    'source_symbol': symbol, 'source_sha256': member['sha256'], 'passes_close_filter': True,
                    'previous_date': str(previous.day) if previous else None}})
        report['entries'] = sorted(entries, key=lambda row: row['ticker'])
        report['summary'] = '부분 복원: 현재 상장 종목군의 검증된 일봉·월봉과 거래소 토요일 실제 거래를 대조했습니다. 원문 미제공·상장폐지 종목은 제외됩니다.'
        report['source_metadata'].update(provider='Same-listing TradingView and TWSE/TPEx original Saturday observations',
            coverage_status='partial', historical_saturday_included=str(SATURDAY),
            verified_daily_symbols=len(curves), unresolved_saturday_listings=errors, unresolved_monthly_listings=monthly_errors,
            original_sources=sources)
        atomic_json(path, report)
        print(f'{session}: {len(entries)} highs checked with the official Saturday', flush=True)
    # Actual exchange trading amount is independent of split-adjusted chart volume.
    path = monthly_report_path(ROOT / 'data/turnover/reports', 'taiwan', SESSIONS[0])
    report = json.loads(path.read_bytes())
    target = backup / 'turnover-2014-12-29.json'
    if not target.exists():
        target.write_bytes(path.read_bytes())
    turns = []
    universe = json.loads((ROOT / 'data/tmp_2014/taiwan-gap-universe.json').read_bytes())
    for row in universe['rows']:
        quote = quotes[row['exchange'], SESSIONS[0]].get(row['name'])
        if quote and quote['bar'].volume > 0:
            turns.append((row, quote))
    entries = []
    for rank, (row, quote) in enumerate(sorted(turns, key=lambda item: (-item[1]['amount'], item[0]['symbol']))[:30], 1):
        member = curves.get(row['symbol'])
        prior = [bar for bar in member['bars'] if bar.day < SESSIONS[0]] if member else []
        today = next((bar for bar in member['bars'] if bar.day == SESSIONS[0]), None) if member else None
        entries.append({'rank': rank, 'ticker': archive_ticker(row), 'name': quote['name'], 'exchange': row['exchange'],
            'price': quote['bar'].close, 'change_pct': (today.close/prior[-1].close-1)*100 if today and prior else None,
            'turnover': quote['amount'], 'currency': 'TWD', 'market_cap': None,
            'sector': row.get('sector') or '미분류', 'industry': row.get('industry') or '업종 정보 미확인', 'source_symbol': row['symbol'],
            'change_verification': {'source': 'Verified same-listing actual closes including official Saturday',
                'previous_date': str(prior[-1].day) if today and prior else None, 'source_sha256': member['sha256'] if member else None}})
    report['entries'] = entries
    report['summary'] = '부분 복원: 현재 상장 종목군의 거래소 실제 거래대금 순위입니다. 등락률은 공식 토요일을 포함한 동일 종목 조정 기준 종가로 대조했습니다.'
    report['source_metadata'].update(provider='TWSE/TPEx exact-date official daily reports', coverage_status='partial',
        ranking='Official exchange actual daily trading amount descending', split_adjusted=False, original_sources=sources,
        historical_saturday_included=str(SATURDAY))
    atomic_json(path, report)
    atomic_json(PROOF, {'date': str(SESSIONS[0]), 'sessions': [str(day) for day in SESSIONS],
        'original_sources': sources, 'unresolved_listings': errors, 'monthly_errors': monthly_errors,
        'histories': {symbol: {'sha256': member['sha256']} for symbol, member in curves.items()},
        'checked_at': datetime.now(timezone.utc).isoformat()})


if __name__ == '__main__':
    main()
