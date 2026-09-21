"""Backfill new-high and turnover calendars from dated Yahoo OHLCV bars.

This recovery path is intentionally separate from the daily TradingView
collector.  It scans the configured current TradingView stock universe, maps
each listing to Yahoo, downloads split-adjusted daily bars, and publishes only
sessions whose per-exchange coverage passes a fail-closed threshold.  Delisted
listings that are no longer in the current scanner universe cannot be restored.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import time as time_module
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from difflib import SequenceMatcher
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from generate_new_high_data import SOURCE_DIR as NEW_HIGH_DIR
from generate_new_high_data import load_markets, validate_report as validate_new_high
from generate_turnover_data import SOURCE_DIR as TURNOVER_DIR
from generate_turnover_data import validate_report as validate_turnover
from new_high_sources.tradingview import _CONFIG, _DEFINITION_URL, _request_json, _text
from refresh_new_highs import atomic_json, collection_date
from turnover_sources.tradingview import _logo_url


SUPPORTED_MARKETS = frozenset({"china", "japan", "europe"})
UNIVERSE_COLUMNS = (
    "name", "description", "exchange", "type", "subtype", "sector",
    "industry", "currency", "logoid",
)
YAHOO_SUFFIXES = {
    "SSE": (".SS",), "SZSE": (".SZ",), "TSE": (".T",),
    "XETR": (".DE",), "LSE": (".L",), "SIX": (".SW",),
    "EURONEXT": (".PA", ".AS", ".BR", ".LS", ".IR"),
}


class BackfillError(ValueError):
    """The historical source cannot prove a complete daily report."""


class NoRequestedSession(BackfillError):
    """A correctly identified listing did not trade in the requested range."""


@dataclass(frozen=True)
class Bar:
    day: date
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class ListingHistory:
    row: dict[str, Any]
    yahoo_symbol: str
    bars: list[Bar]


def _number(value: Any, *, positive: bool = False, nonnegative: bool = False) -> float | None:
    if type(value) not in (int, float) or not math.isfinite(value):
        return None
    number = float(value)
    if positive and number <= 0 or nonnegative and number < 0:
        return None
    return number


def requested_dates(start: date, end: date) -> list[date]:
    if end < start:
        raise BackfillError("end date must not precede start date")
    return [
        start + timedelta(days=offset)
        for offset in range((end - start).days + 1)
        if (start + timedelta(days=offset)).weekday() < 5
    ]


def scan_universe(market_id: str, *, timeout: float = 30, page_size: int = 1000) -> list[dict[str, Any]]:
    scanner, exchanges = _CONFIG[market_id]
    endpoint = f"https://scanner.tradingview.com/{scanner}/scan"
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    total: int | None = None
    while total is None or len(rows) < total:
        start = len(rows)
        payload = {
            "filter": [
                {"left": "type", "operation": "equal", "right": "stock"},
                {"left": "exchange", "operation": "in_range", "right": list(exchanges)},
            ],
            "columns": list(UNIVERSE_COLUMNS),
            "sort": {"sortBy": "name", "sortOrder": "asc"},
            "range": [start, start + page_size],
        }
        response = _request_json(endpoint, payload, timeout)
        if not isinstance(response, dict) or type(response.get("totalCount")) is not int:
            raise BackfillError(f"{market_id}: malformed TradingView universe response")
        count, page = response["totalCount"], response.get("data")
        if count <= 0 or count > 100_000 or not isinstance(page, list):
            raise BackfillError(f"{market_id}: invalid TradingView universe")
        if total is not None and count != total:
            raise BackfillError(f"{market_id}: TradingView universe changed during pagination")
        total = count
        if len(page) != min(page_size, total - start):
            raise BackfillError(f"{market_id}: incomplete TradingView page at {start}")
        for item in page:
            if not isinstance(item, dict) or not _text(item.get("s")):
                raise BackfillError(f"{market_id}: malformed TradingView symbol")
            symbol, values = item["s"], item.get("d")
            if symbol in seen or not isinstance(values, list) or len(values) != len(UNIVERSE_COLUMNS):
                raise BackfillError(f"{symbol}: duplicate or incomplete TradingView row")
            row = dict(zip(UNIVERSE_COLUMNS, values), symbol=symbol)
            if row["exchange"] not in exchanges or row["type"] != "stock":
                raise BackfillError(f"{symbol}: TradingView did not honor universe filters")
            seen.add(symbol)
            rows.append(row)
    return rows


def yahoo_candidates(row: dict[str, Any]) -> list[str]:
    exchange, code = row["exchange"], row["name"]
    suffixes = YAHOO_SUFFIXES.get(exchange)
    if suffixes is None:
        raise BackfillError(f"{row['symbol']}: no Yahoo exchange mapping")
    # Yahoo represents many share classes with a hyphen where TradingView uses
    # a dot. Try the literal code first because dots are valid on some venues.
    codes = [code]
    normalized = code.replace("/", "-").replace(".", "-")
    if normalized != code:
        codes.append(normalized)
    return list(dict.fromkeys(f"{candidate}{suffix}" for suffix in suffixes for candidate in codes))


def _company_name_matches(expected: str, meta: dict[str, Any]) -> bool:
    ignored = {"a", "b", "class", "co", "company", "corp", "corporation", "group",
               "inc", "limited", "ltd", "nv", "ordinary", "plc", "sa", "se", "shares", "ag"}
    def tokens(value: str) -> list[str]:
        return [token for token in re.findall(r"[a-z0-9]+", value.casefold()) if token not in ignored]
    left = tokens(expected)
    names = [value for value in (meta.get("longName"), meta.get("shortName")) if isinstance(value, str)]
    if not left or not names:
        return True
    for name in names:
        right = tokens(name)
        if set(left) & set(right) or SequenceMatcher(None, "".join(left), "".join(right)).ratio() >= 0.72:
            return True
    return False


def _cache_path(cache_dir: Path, namespace: str, key: str) -> Path:
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return cache_dir / namespace / f"{digest}.json"


def request_yahoo(symbol: str, *, period1: date | None, period2: date | None,
                  range_name: str | None, interval: str, timeout: float,
                  cache_dir: Path, retries: int = 4) -> dict[str, Any]:
    params: dict[str, str] = {"interval": interval, "events": "splits", "includePrePost": "false"}
    if range_name:
        params["range"] = range_name
    else:
        assert period1 is not None and period2 is not None
        params["period1"] = str(int(datetime.combine(period1, time(), timezone.utc).timestamp()))
        params["period2"] = str(int(datetime.combine(period2, time(), timezone.utc).timestamp()))
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol, safe='')}?{urlencode(params)}"
    cache_path = _cache_path(cache_dir, f"{interval}-{range_name or 'dated'}", url)
    if cache_path.exists():
        try:
            return json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            cache_path.unlink(missing_ok=True)
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 stock-peer-calendar", "Accept": "application/json"})
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            with urlopen(request, timeout=timeout) as response:
                payload = json.load(response)
            chart = payload.get("chart") if isinstance(payload, dict) else None
            if not isinstance(chart, dict) or chart.get("error") or not chart.get("result"):
                raise BackfillError(f"{symbol}: empty Yahoo chart response")
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = cache_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(payload, ensure_ascii=False, allow_nan=False), encoding="utf-8")
            os.replace(temporary, cache_path)
            return payload
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, BackfillError) as exc:
            last_error = exc
            if isinstance(exc, HTTPError) and exc.code == 404:
                break
            if attempt + 1 < retries:
                time_module.sleep(0.5 * (attempt + 1))
    raise BackfillError(f"{symbol}: Yahoo history unavailable: {last_error}")


def _chart_result(payload: dict[str, Any], symbol: str) -> dict[str, Any]:
    try:
        return payload["chart"]["result"][0]
    except (KeyError, IndexError, TypeError) as exc:
        raise BackfillError(f"{symbol}: malformed Yahoo chart response") from exc


def parse_bars(payload: dict[str, Any], symbol: str, timezone_name: str, *,
               merge_duplicates: bool = False) -> list[Bar]:
    result = _chart_result(payload, symbol)
    timestamps = result.get("timestamp") or []
    quotes = (result.get("indicators") or {}).get("quote") or []
    if not isinstance(timestamps, list) or not quotes or not isinstance(quotes[0], dict):
        raise BackfillError(f"{symbol}: missing Yahoo OHLCV")
    quote_row = quotes[0]
    columns = {field: quote_row.get(field) or [] for field in ("open", "high", "low", "close", "volume")}
    if any(len(values) != len(timestamps) for values in columns.values()):
        raise BackfillError(f"{symbol}: inconsistent Yahoo OHLCV lengths")
    split_events = (result.get("events") or {}).get("splits") or {}
    splits: list[tuple[int, float]] = []
    if isinstance(split_events, dict):
        for event in split_events.values():
            if not isinstance(event, dict):
                continue
            stamp = _number(event.get("date"), positive=True)
            numerator = _number(event.get("numerator"), positive=True)
            denominator = _number(event.get("denominator"), positive=True)
            if stamp and numerator and denominator:
                splits.append((int(stamp), denominator / numerator))
    zone = ZoneInfo(timezone_name)
    bars: list[Bar] = []
    for index, stamp_value in enumerate(timestamps):
        stamp = _number(stamp_value, positive=True)
        values = {field: _number(columns[field][index], nonnegative=field == "volume", positive=field != "volume")
                  for field in columns}
        if stamp is None or any(value is None for value in values.values()):
            continue
        price_factor = math.prod(factor for split_stamp, factor in splits if int(stamp) < split_stamp)
        volume_factor = 1 / price_factor if price_factor else 1
        bars.append(Bar(
            day=datetime.fromtimestamp(stamp, timezone.utc).astimezone(zone).date(),
            open=values["open"] * price_factor,
            high=values["high"] * price_factor,
            low=values["low"] * price_factor,
            close=values["close"] * price_factor,
            volume=values["volume"] * volume_factor,
        ))
    bars.sort(key=lambda bar: bar.day)
    if len({bar.day for bar in bars}) != len(bars):
        if not merge_duplicates:
            raise BackfillError(f"{symbol}: duplicate Yahoo daily date")
        merged: dict[date, Bar] = {}
        for bar in bars:
            previous = merged.get(bar.day)
            merged[bar.day] = bar if previous is None else Bar(
                day=bar.day, open=previous.open, high=max(previous.high, bar.high),
                low=min(previous.low, bar.low), close=bar.close,
                volume=previous.volume + bar.volume,
            )
        bars = sorted(merged.values(), key=lambda bar: bar.day)
    return bars


def fetch_listing_history(row: dict[str, Any], start: date, end: date, *, timeout: float,
                          cache_dir: Path) -> ListingHistory:
    timezone_name = _CONFIG[{"TSE": "japan", "SSE": "china", "SZSE": "china"}.get(row["exchange"], "europe")][1][row["exchange"]]
    errors = []
    for candidate in yahoo_candidates(row):
        try:
            payload = request_yahoo(
                candidate, period1=start - timedelta(days=370), period2=end + timedelta(days=2),
                range_name=None, interval="1d", timeout=timeout, cache_dir=cache_dir,
            )
            bars = parse_bars(payload, candidate, timezone_name)
            meta = _chart_result(payload, candidate).get("meta") or {}
            if str(meta.get("instrumentType", "")).upper() not in {"EQUITY", ""}:
                raise BackfillError(f"{candidate}: not an equity")
            if not _company_name_matches(str(row.get("description") or row["name"]), meta):
                raise BackfillError(f"{candidate}: Yahoo company name does not match TradingView")
            if not any(start <= bar.day <= end for bar in bars):
                raise NoRequestedSession(f"{candidate}: no requested session")
            return ListingHistory(row=row, yahoo_symbol=candidate, bars=bars)
        except NoRequestedSession:
            # The symbol identity is proven. Trying another venue suffix could
            # incorrectly substitute a different active listing with the same code.
            raise
        except BackfillError as exc:
            errors.append(str(exc))
    raise BackfillError(errors[-1] if errors else f"{row['symbol']}: no Yahoo candidates")


def daily_candidates(history: ListingHistory, sessions: set[date]) -> dict[date, tuple[Bar, float, bool]]:
    result: dict[date, tuple[Bar, float, bool]] = {}
    bars = history.bars
    for index, bar in enumerate(bars):
        if bar.day not in sessions:
            continue
        lookback = bar.day - timedelta(weeks=52)
        high_52 = max((item.high for item in bars if lookback <= item.day <= bar.day), default=bar.high)
        previous_close = bars[index - 1].close if index else None
        passes_close = bar.close >= bar.open and (previous_close is None or bar.close >= previous_close)
        change_pct = 0.0 if previous_close is None else (bar.close / previous_close - 1) * 100
        if bar.high >= high_52 * (1 - 1e-10):
            result[bar.day] = (bar, change_pct, passes_close)
    return result


def fetch_prior_all_time_high(history: ListingHistory, start: date, *, timeout: float,
                              cache_dir: Path) -> float:
    exchange = history.row["exchange"]
    timezone_name = _CONFIG[{"TSE": "japan", "SSE": "china", "SZSE": "china"}.get(exchange, "europe")][1][exchange]
    payload = request_yahoo(
        history.yahoo_symbol, period1=None, period2=None, range_name="max", interval="1mo",
        timeout=timeout, cache_dir=cache_dir,
    )
    bars = parse_bars(payload, history.yahoo_symbol, timezone_name, merge_duplicates=True)
    return max((bar.high for bar in bars if bar.day < start.replace(day=1)), default=0.0)


def published_exchange(exchange: str) -> str:
    return "XETRA" if exchange == "XETR" else exchange


def archive_ticker(row: dict[str, Any]) -> str:
    suffixes = {"SSE": ".SS", "SZSE": ".SZ", "TSE": ".T"}
    return row["name"] + suffixes[row["exchange"]] if row["exchange"] in suffixes else row["symbol"]


def build_reports(market_id: str, start: date, end: date, *, workers: int = 24,
                  timeout: float = 30, minimum_coverage_ratio: float = 0.7,
                  cache_dir: Path) -> tuple[dict[date, dict], dict[date, dict]]:
    if market_id not in SUPPORTED_MARKETS:
        raise BackfillError(f"unsupported market: {market_id}")
    sessions = set(requested_dates(start, end))
    universe = scan_universe(market_id, timeout=timeout)
    histories: list[ListingHistory] = []
    failures: list[str] = []
    inactive: list[str] = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(fetch_listing_history, row, start, end, timeout=timeout,
                                   cache_dir=cache_dir): row for row in universe}
        for completed, future in enumerate(as_completed(futures), start=1):
            try:
                histories.append(future.result())
            except NoRequestedSession as exc:
                inactive.append(f"{futures[future]['symbol']}: {exc}")
            except BackfillError as exc:
                failures.append(f"{futures[future]['symbol']}: {exc}")
            if completed % 500 == 0:
                print(f"{market_id}: history {completed}/{len(universe)}; ok={len(histories)} inactive={len(inactive)} failed={len(failures)}", flush=True)
    relevant = len(histories) + len(failures)
    ratio = len(histories) / relevant if relevant else 0
    if ratio < minimum_coverage_ratio:
        raise BackfillError(
            f"{market_id}: Yahoo coverage {len(histories)}/{relevant} active/mappable listings ({ratio:.1%}) "
            f"is below {minimum_coverage_ratio:.0%}"
        )
    by_exchange: dict[str, tuple[int, int]] = {}
    for exchange in _CONFIG[market_id][1]:
        failed_symbols = {item.split(": ", 1)[0] for item in failures}
        covered = sum(history.row["exchange"] == exchange for history in histories)
        failed = sum(row["exchange"] == exchange and row["symbol"] in failed_symbols for row in universe)
        total = covered + failed
        by_exchange[exchange] = (covered, total)
        if total and covered / total < minimum_coverage_ratio:
            raise BackfillError(f"{market_id}/{exchange}: Yahoo coverage {covered}/{total} is incomplete")

    matched: dict[date, list[tuple[ListingHistory, Bar]]] = {session: [] for session in sessions}
    candidates: dict[str, dict[date, tuple[Bar, float, bool]]] = {}
    for history in histories:
        candidate_days = daily_candidates(history, sessions)
        if candidate_days:
            candidates[history.row["symbol"]] = candidate_days
        for bar in history.bars:
            if bar.day in sessions:
                matched[bar.day].append((history, bar))
    trading_sessions = sorted(session for session, rows in matched.items() if rows)
    for session in trading_sessions:
        exchanges = {history.row["exchange"] for history, _bar in matched[session]}
        missing = set(_CONFIG[market_id][1]) - exchanges
        if missing:
            raise BackfillError(f"{market_id} {session}: missing exchanges {sorted(missing)}")
        if len(matched[session]) < len(histories) * 0.45:
            raise BackfillError(f"{market_id} {session}: suspiciously low session coverage")

    candidate_histories = [history for history in histories if history.row["symbol"] in candidates]
    prior_all_time: dict[str, float] = {}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(fetch_prior_all_time_high, history, start, timeout=timeout,
                                   cache_dir=cache_dir): history for history in candidate_histories}
        for completed, future in enumerate(as_completed(futures), start=1):
            history = futures[future]
            try:
                prior_all_time[history.row["symbol"]] = future.result()
            except BackfillError as exc:
                raise BackfillError(f"{history.row['symbol']}: all-time history failed: {exc}") from exc
            if completed % 200 == 0:
                print(f"{market_id}: all-time {completed}/{len(candidate_histories)}", flush=True)

    fetched_at = datetime.now(timezone.utc).isoformat()
    new_reports: dict[date, dict] = {}
    turnover_reports: dict[date, dict] = {}
    for session in trading_sessions:
        new_entries = []
        for history in histories:
            evidence = candidates.get(history.row["symbol"], {}).get(session)
            if evidence is None:
                continue
            bar, change_pct, passes_close = evidence
            if not passes_close:
                continue
            same_month_high = max(
                item.high for item in history.bars
                if item.day.year == session.year and item.day.month == session.month and item.day <= session
            )
            all_time_level = max(prior_all_time[history.row["symbol"]], same_month_high)
            high_type = "all_time" if bar.high >= all_time_level * (1 - 1e-10) else "52_week"
            row = history.row
            sector = row["sector"].strip() if _text(row.get("sector")) else "미분류"
            industry = row["industry"].strip() if _text(row.get("industry")) else "업종 정보 미확인"
            name = row["description"].strip() if _text(row.get("description")) else row["name"]
            new_entries.append({
                "ticker": archive_ticker(row), "name": name,
                "exchange": published_exchange(row["exchange"]), "category": sector,
                "high_type": high_type, "reason": f"업종: {sector} · {industry}",
                "description": f"{name} · {industry}", "change_pct": change_pct,
                "session_open": bar.open, "session_close": bar.close,
                "currency": row["currency"].strip().upper(), "source_symbol": row["symbol"],
                "high_verification": {
                    "source": "Yahoo Finance split-adjusted daily/monthly history",
                    "source_url": f"https://finance.yahoo.com/quote/{quote(history.yahoo_symbol, safe='')}/history/",
                    "date": session.isoformat(), "daily_high": bar.high,
                    "prior_all_time_or_current_month_high": all_time_level,
                    "passes_close_filter": passes_close, "yahoo_symbol": history.yahoo_symbol,
                },
            })
        new_entries.sort(key=lambda entry: (entry["exchange"], entry["ticker"]))

        ranked = sorted(
            ((history, bar, bar.close * bar.volume) for history, bar in matched[session] if bar.volume > 0),
            key=lambda item: (-item[2], item[0].row["symbol"]),
        )[:30]
        turnover_entries = []
        for rank, (history, bar, turnover) in enumerate(ranked, start=1):
            row = history.row
            name = row["description"].strip() if _text(row.get("description")) else row["name"]
            sector = row["sector"].strip() if _text(row.get("sector")) else "미분류"
            industry = row["industry"].strip() if _text(row.get("industry")) else "업종 정보 미확인"
            bars_before = [item for item in history.bars if item.day < session]
            previous_close = bars_before[-1].close if bars_before else None
            change_pct = None if previous_close is None else (bar.close / previous_close - 1) * 100
            turnover_entries.append({
                "rank": rank, "ticker": archive_ticker(row), "name": name,
                "exchange": published_exchange(row["exchange"]), "price": bar.close,
                "change_pct": change_pct, "turnover": turnover,
                "currency": row["currency"].strip().upper(), "market_cap": None,
                "sector": sector, "industry": industry, "source_symbol": row["symbol"],
                **({"logo_url": logo} if (logo := _logo_url(row.get("logoid"))) else {}),
            })

        metadata = {
            "provider": "Yahoo Finance chart history",
            "universe_provider": "TradingView public scanner", "fetched_at": fetched_at,
            "universe": "Current TradingView-listed stock instruments; ETFs excluded; delisted historical listings excluded",
            "scanned_symbols": len(universe), "history_symbols": len(histories),
            "inactive_symbols": len(inactive), "failed_symbols": len(failures), "coverage_ratio": ratio,
            "coverage_by_exchange": {key: {"covered": value[0], "total": value[1]} for key, value in by_exchange.items()},
            "session_symbols": len(matched[session]), "split_adjusted": True,
        }
        new_reports[session] = {
            "schema_version": 1, "market": market_id, "date": session.isoformat(),
            "summary": "Yahoo Finance 과거 일봉으로 복원했습니다. 당일 장중 고가가 52주·전체기간 고가에 도달하고 음봉 또는 전일 대비 하락 마감이 아닌 종목입니다.",
            "sources": [
                {"label": "Yahoo Finance historical data", "url": "https://finance.yahoo.com/"},
                {"label": "TradingView stock universe", "url": "https://www.tradingview.com/screener/"},
                {"label": "TradingView 신고가 산정 기준", "url": _DEFINITION_URL},
            ], "entries": new_entries, "source_metadata": metadata, "collected_at": fetched_at,
        }
        turnover_reports[session] = {
            "schema_version": 1, "market": market_id, "date": session.isoformat(),
            "summary": "Yahoo Finance 과거 일봉의 종가×거래량 기준 거래대금 상위 30개 종목입니다.",
            "sources": [
                {"label": "Yahoo Finance historical data", "url": "https://finance.yahoo.com/"},
                {"label": "TradingView stock universe", "url": "https://www.tradingview.com/screener/"},
            ], "entries": turnover_entries,
            "source_metadata": {**metadata, "ranking": "split-adjusted close × volume descending"},
        }
    return new_reports, turnover_reports


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--market", choices=sorted(SUPPORTED_MARKETS), required=True)
    parser.add_argument("--start", required=True, type=date.fromisoformat)
    parser.add_argument("--end", required=True, type=date.fromisoformat)
    parser.add_argument("--workers", type=int, default=24)
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--minimum-coverage-ratio", type=float, default=0.7)
    parser.add_argument("--cache-dir", type=Path, default=Path(__file__).resolve().parents[1] / "data" / "tmp_calendar_history")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.workers <= 64:
        parser.error("--workers must be between 1 and 64")
    if not 0.5 <= args.minimum_coverage_ratio <= 1:
        parser.error("--minimum-coverage-ratio must be between 0.5 and 1")
    configured_market = next(market for market in load_markets(NEW_HIGH_DIR) if market["id"] == args.market)
    now = datetime.now(timezone.utc)
    completed = collection_date(configured_market, now)
    if completed is None:
        local_day = now.astimezone(ZoneInfo(configured_market["timezone"])).date()
        completed = local_day - timedelta(days=1)
        while completed.weekday() >= 5:
            completed -= timedelta(days=1)
    effective_end = min(args.end, completed)
    if effective_end < args.start:
        parser.error(f"no completed candidate session between {args.start} and {args.end}")
    if effective_end != args.end:
        print(f"{args.market}: excluding sessions after {effective_end} because the local close is not complete", flush=True)
    reports_new, reports_turnover = build_reports(
        args.market, args.start, effective_end, workers=args.workers, timeout=args.timeout,
        minimum_coverage_ratio=args.minimum_coverage_ratio, cache_dir=args.cache_dir,
    )
    markets_new = {market["id"]: market for market in load_markets(NEW_HIGH_DIR)}
    markets_turnover = {market["id"]: market for market in load_markets(TURNOVER_DIR)}
    for session in sorted(reports_new):
        new_path = NEW_HIGH_DIR / "reports" / args.market / f"{session}.json"
        turnover_path = TURNOVER_DIR / "reports" / args.market / f"{session}.json"
        wrote = []
        if args.force or not new_path.exists():
            validate_new_high(reports_new[session], new_path, NEW_HIGH_DIR / "reports", markets_new)
            atomic_json(new_path, reports_new[session])
            wrote.append(f"new-high={len(reports_new[session]['entries'])}")
        if args.force or not turnover_path.exists():
            validate_turnover(reports_turnover[session], turnover_path, TURNOVER_DIR / "reports", markets_turnover)
            atomic_json(turnover_path, reports_turnover[session])
            wrote.append("turnover=30")
        print(f"{args.market} {session}: {', '.join(wrote) if wrote else 'existing reports preserved'}", flush=True)


if __name__ == "__main__":
    main()
