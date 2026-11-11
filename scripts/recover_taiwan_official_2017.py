"""Restore Saturday sessions from dated TWSE/TPEx originals.

Both public chart providers omit these dates. Preserve the original unadjusted
exchange rows; align to a chart's split basis only when all OHLC observations
on the immediately preceding and following sessions verify the same factor.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from http.client import IncompleteRead
from urllib.request import Request, urlopen
import hashlib
import json
import math
import ssl
import statistics
import time

from archive_paths import monthly_report_path
from backfill_european_new_highs import chart_bars, candidates, classify_high, cached_chart
from backfill_yahoo_calendars import Bar, archive_ticker
from generate_new_high_data import SOURCE_DIR, load_markets, validate_report
from generate_turnover_data import validate_report as validate_turnover
from refresh_new_highs import atomic_json
from quote_sources.tradingview_chart import ChartHistoryError

ROOT = SOURCE_DIR.parent.parent
CACHE = ROOT / 'data/tmp_2017/taiwan-official'
DAYS = [date(2017, 2, 18), date(2017, 6, 3), date(2017, 9, 30)]


def source_url(exchange, day):
    if exchange == 'TWSE':
        return f'https://www.twse.com.tw/exchangeReport/MI_INDEX?response=json&date={day:%Y%m%d}&type=ALLBUT0999'
    return f'https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes?date={day:%Y/%m/%d}&id=&response=json'


def number(value):
    try:
        result = float(str(value).replace(',', '').strip())
    except ValueError:
        return None
    return result if math.isfinite(result) else None


def original(exchange, day):
    url = source_url(exchange, day)
    path = CACHE / (hashlib.sha256(url.encode()).hexdigest()+'.json')
    if not path.exists():
        context = ssl.create_default_context()
        # Python 3.14's new strict flag rejects these legacy exchange chains.
        # Certificate-chain and hostname verification remain enabled.
        context.verify_flags &= ~ssl.VERIFY_X509_STRICT
        for attempt in range(3):
            try:
                with urlopen(Request(url, headers={'User-Agent': 'Mozilla/5.0 Stock Study research'}),
                             timeout=40, context=context) as response:
                    raw = response.read()
                break
            except (OSError, IncompleteRead):
                if attempt == 2:
                    raise
                time.sleep(attempt+1)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    raw = path.read_bytes()
    payload = json.loads(raw)
    if payload.get('date') != day.strftime('%Y%m%d') or payload.get('stat') != 'ok' and payload.get('stat') != 'OK':
        raise ValueError(f'Official source returned another date or failed: {exchange}/{day}')
    metadata = {'url': url, 'sha256': hashlib.sha256(raw).hexdigest(),
                'cache': path.relative_to(ROOT).as_posix(), 'exchange': exchange, 'date': str(day)}
    atomic_json(path.with_suffix('.source.json'), metadata)
    fields = ['證券代號', '證券名稱', '成交股數', '成交金額', '開盤價', '最高價', '最低價', '收盤價'] if exchange == 'TWSE' else ['代號', '名稱', '成交股數', '成交金額(元)', '開盤', '最高', '最低', '收盤']
    table = next(table for table in payload['tables'] if all(field in table.get('fields', []) for field in fields))
    rows = {}
    for values in table['data']:
        value = dict(zip(table['fields'], values))
        code, name = value[fields[0]], value[fields[1]]
        volume, amount, opening, high, low, close = [number(value[field]) for field in fields[2:]]
        if any(v is None for v in [volume, amount, opening, high, low, close]):
            continue
        if min(opening, high, low, close) <= 0 or volume < 0 or amount < 0:
            raise ValueError(f'Invalid official quote: {exchange}/{day}/{code}')
        if low > min(opening, close) or high < max(opening, close):
            raise ValueError('Official OHLC bounds differ')
        if code in rows:
            raise ValueError('Duplicated official code')
        rows[code] = {'bar': Bar(day, opening, high, low, close, volume), 'amount': amount, 'name': name}
    if len(rows) < 600:
        raise ValueError(f'Incomplete official universe: {exchange}/{day}')
    return rows, metadata


def verified_factor(before, after, bars):
    by_day = {bar.day: bar for bar in bars}
    pairs = [(original, by_day[original.day]) for original in [before, after] if original.day in by_day]
    if len(pairs) != 2:
        raise ValueError('Both bracketing original sessions are required')
    factor = statistics.median(chart.close / raw.close for raw, chart in pairs)
    if not factor > 0 or not math.isfinite(factor):
        raise ValueError('Invalid split-basis factor')
    for raw, chart in pairs:
        for field in ['open', 'high', 'low', 'close']:
            if not math.isclose(getattr(raw, field)*factor, getattr(chart, field), rel_tol=1e-5, abs_tol=.005):
                raise ValueError('Split basis differs across bracketing OHLC sessions')
    return factor


def main():
    universe_path = ROOT / 'data/tmp_2017/taiwan-gap-universe.json'
    universe = json.loads(universe_path.read_bytes())
    rows = universe['rows']
    cache = ROOT / 'data/tmp_tradingview_chart'
    now = datetime.now(timezone.utc).isoformat()
    for day in DAYS:
        published = SOURCE_DIR / 'reports/taiwan' / f'{day}.json'
        monetary_path = monthly_report_path(ROOT/'data/turnover/reports', 'taiwan', day)
        proof_path = ROOT / f'data/information-audit/2017/taiwan-official-recovery-{day}.json'
        if published.exists() and monetary_path.exists() and proof_path.exists():
            if json.loads(proof_path.read_bytes())['date'] != str(day):
                raise ValueError('Stored recovery proof has another date')
            print(f'Preserved verified official Saturday {day}', flush=True)
            continue
        print(f'Restore official Saturday {day}', flush=True)
        originals, sources = {}, []
        for exchange in ['TWSE', 'TPEX']:
            for session in [day-timedelta(days=1), day, day+timedelta(days=2)]:
                quotes, metadata = original(exchange, session)
                originals[exchange, session] = quotes
                sources.append(metadata)
        evidence, failures, members, turns = {}, {}, {}, []
        for row in rows:
            exchange, code = row['exchange'], row['name']
            quote = originals[exchange, day].get(code)
            if not quote or quote['bar'].volume <= 0:
                continue
            turns.append((row, quote))
            path = cache / '1D' / (hashlib.sha256(f"{row['symbol']}:1D:3200".encode()).hexdigest()+'.json')
            if not path.exists():
                failures[row['symbol']] = 'Verified daily history unavailable'
                continue
            try:
                payload = json.loads(path.read_bytes())
                bars = chart_bars(payload, row)
                before = originals[exchange, day-timedelta(days=1)][code]['bar']
                after = originals[exchange, day+timedelta(days=2)][code]['bar']
                factor = verified_factor(before, after, bars)
                raw = quote['bar']
                restored = Bar(day, raw.open*factor, raw.high*factor, raw.low*factor, raw.close*factor, raw.volume/factor)
                if any(bar.day == day for bar in bars):
                    raise ValueError('Expected missing Saturday already appears in original chart')
                combined = sorted([*bars, restored], key=lambda bar: bar.day)
                proof = {'factor': factor, 'verified_dates': [str(before.day), str(after.day)],
                         'original_bar': {'date': str(day), **{field: getattr(raw, field) for field in ['open','high','low','close','volume']}},
                         'source_url': source_url(exchange, day), 'chart_cache': path.relative_to(ROOT).as_posix(),
                         'chart_sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
                members[row['symbol']] = {'row': row, 'bar': restored, 'proof': proof, 'payload': payload, 'bars': combined}
                checks = candidates(combined, {day})
                if day in checks:
                    evidence[row['symbol']] = checks[day]
            except (ValueError, KeyError, ChartHistoryError) as error:
                failures[row['symbol']] = str(error)
        for exchange in ['TWSE', 'TPEX']:
            if sum(member['row']['exchange'] == exchange for member in members.values()) < 400:
                raise ValueError(f'Insufficient independently verified price bases: {exchange}/{day}')
        entries = []
        monthly_errors = {}
        def classify(symbol):
            member = members[symbol]
            monthly = cached_chart(member['row'], '1M', 1500, cache_dir=cache, timeout=25, required_end=day.replace(day=1)-timedelta(days=1))
            return symbol, classify_high(member['bars'], chart_bars(monthly, member['row']), day, day)
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {symbol: pool.submit(classify, symbol) for symbol in evidence}
            for symbol, future in futures.items():
                try:
                    _, (kind, level) = future.result()
                    member = members[symbol]
                    row, bar = member['row'], member['bar']
                    previous = evidence[symbol]['previous']
                    entries.append({'ticker': archive_ticker(row), 'name': originals[row['exchange'], day][row['name']]['name'],
                        'exchange': row['exchange'], 'category': row.get('sector') or '미분류', 'high_type': kind,
                        'reason': '공식 거래소 토요일 실제 거래 확인 · 이전 52주와 전체기간 고가 대조',
                        'description': row['description'], 'currency': 'TWD', 'source_symbol': symbol,
                        'change_pct': (bar.close/previous.close-1)*100 if previous else None,
                        'session_open': bar.open, 'session_close': bar.close, 'session_volume': bar.volume,
                        'high_verification': {'source': 'Official exchange Saturday quote aligned to verified same-listing split basis',
                            'date': str(day), 'daily_high': bar.high, 'prior_all_time_or_current_month_high': level, **member['proof']}})
                except (ValueError, ChartHistoryError) as error:
                    monthly_errors[symbol] = str(error)
        metadata = {'provider': 'TWSE/TPEx exact-date official daily reports and verified same-listing TradingView historical basis',
            'fetched_at': now, 'universe_fetched_at': universe['fetched_at'], 'scanned_symbols': len(rows),
            'session_symbols': len(turns), 'history_symbols': len(members), 'coverage_status': 'partial',
            'universe': 'Current listed stock universe; historical delisted stocks excluded',
            'original_sources': sources, 'unresolved_listings': failures, 'unresolved_monthly_listings': monthly_errors,
            'split_adjusted': True, 'session': 'regular', 'recovery_reason': 'Both chart providers omit the official Saturday session'}
        links = [{'label': f'{exchange} official historical daily report', 'url': source_url(exchange, day)} for exchange in ['TWSE','TPEX']]
        summary = '部分復元 · 부분 복원: 공식 거래소 토요일 실제 거래를 사용했습니다. 신고가는 전후 두 거래일 OHLC의 조정 기준이 일치하는 종목만 대조했으며, 원본 미지원·상장폐지 종목은 제외합니다.'
        report = {'schema_version': 1, 'market': 'taiwan', 'date': str(day), 'summary': summary,
                  'sources': links, 'entries': sorted(entries, key=lambda row: row['ticker']), 'source_metadata': metadata, 'collected_at': now}
        path = SOURCE_DIR / 'reports/taiwan' / f'{day}.json'
        validate_report(report, path, SOURCE_DIR/'reports', {row['id']: row for row in load_markets(SOURCE_DIR)})
        turnover = []
        for rank, (row, quote) in enumerate(sorted(turns, key=lambda item: (-item[1]['amount'], item[0]['symbol']))[:30], 1):
            bar = quote['bar']
            before = originals[row['exchange'], day-timedelta(days=1)].get(row['name'])
            turnover.append({'rank': rank, 'ticker': archive_ticker(row), 'name': quote['name'], 'exchange': row['exchange'],
                'price': bar.close, 'change_pct': (bar.close/before['bar'].close-1)*100 if before else None,
                'turnover': quote['amount'], 'currency': 'TWD', 'market_cap': None,
                'sector': row.get('sector') or '미분류', 'industry': row.get('industry') or '업종 정보 미확인', 'source_symbol': row['symbol']})
        monetary = {**report, 'summary': '부분 복원: 현재 상장 종목군의 공식 거래소 확정 거래대금 순위입니다. 상장폐지 종목은 제외합니다.',
            'entries': turnover, 'source_metadata': {**metadata, 'split_adjusted': False, 'ranking': 'Official exchange actual daily trading amount descending'}}
        target = ROOT / 'data/turnover'
        tpath = monthly_report_path(target/'reports', 'taiwan', day)
        validate_turnover(monetary, tpath, target/'reports', {row['id']: row for row in load_markets(target)})
        atomic_json(ROOT / f'data/information-audit/2017/taiwan-official-recovery-{day}.json',
            {'date': str(day), 'verified_chart_members': len(members), 'official_members': len(turns),
             'metadata': metadata, 'members': {symbol: member['proof'] for symbol, member in members.items()}})
        if path.exists() or tpath.exists():
            raise ValueError('Preserve existing Saturday reports')
        atomic_json(path, report)
        atomic_json(tpath, monetary)
        print(f'{day}: {len(entries)} new highs, 30 official turnover entries, {len(members)} verified price bases, {len(failures)} exceptions', flush=True)


if __name__ == '__main__':
    main()
