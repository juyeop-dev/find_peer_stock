"""Backfill recent daily new-high reports from dated TradingView scanner bars.

Only Japan is enabled for now.  The scanner and report builder are deliberately
market-parameterized so another validated market (the US is the next planned
one) can be enabled without duplicating the historical-bar logic.
"""

from __future__ import annotations

import argparse
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from generate_new_high_data import SOURCE_DIR, load_markets, validate_report
from new_high_sources.tradingview import (
    COLUMNS,
    _CONFIG,
    _DEFINITION_URL,
    _high_type,
    _number,
    _passes_close_filter,
    _request_json,
    _text,
    _ticker,
    TradingViewSourceError,
)
from refresh_new_highs import atomic_json


SUPPORTED_BACKFILL_MARKETS = frozenset({"japan"})
SUPPORTED_HISTORICAL_SCAN_MARKETS = frozenset(_CONFIG)
IDENTITY_COLUMNS = COLUMNS[:7] + ("currency",)
BAR_COLUMNS = ("change", "open", "high", "low", "close", "price_52_week_high", "High.All", "time", "volume")


def requested_dates(start: date, end: date) -> list[date]:
    if end < start:
        raise ValueError("end date must not precede start date")
    return [
        start + timedelta(days=offset)
        for offset in range((end - start).days + 1)
        if (start + timedelta(days=offset)).weekday() < 5
    ]


def indexed(field: str, offset: int) -> str:
    if type(offset) is not int or offset < 0:
        raise ValueError("bar offset must be a nonnegative integer")
    return field if offset == 0 else f"{field}[{offset}]"


def historical_columns(max_offset: int) -> tuple[str, ...]:
    if type(max_offset) is not int or not 0 <= max_offset <= 260:
        raise ValueError("max_offset must be between 0 and 260")
    return tuple(IDENTITY_COLUMNS) + tuple(
        indexed(field, offset)
        for offset in range(max_offset + 1)
        for field in BAR_COLUMNS
    )


def default_max_offset(start: date, as_of: date) -> int:
    if start > as_of:
        raise ValueError("cannot backfill a future date")
    # Weekdays approximate exchange sessions; five extra slots cover holidays.
    weekdays = sum(
        (start + timedelta(days=offset)).weekday() < 5
        for offset in range((as_of - start).days + 1)
    )
    return min(260, weekdays + 5)


def scan_historical(market_id: str, max_offset: int, timeout: float = 30,
                    page_size: int = 500, symbols: set[str] | None = None) -> list[dict[str, Any]]:
    if market_id not in SUPPORTED_HISTORICAL_SCAN_MARKETS:
        raise TradingViewSourceError(f"Unsupported historical scanner market: {market_id}")
    if not _number(timeout) or timeout <= 0:
        raise TradingViewSourceError("timeout must be positive and finite")
    if type(page_size) is not int or not 1 <= page_size <= 5000:
        raise TradingViewSourceError("page_size must be an integer between 1 and 5000")
    scanner, exchanges = _CONFIG[market_id]
    columns = historical_columns(max_offset)
    endpoint = f"https://scanner.tradingview.com/{scanner}/scan"
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    total: int | None = None
    while total is None or len(rows) < total:
        start = len(rows)
        filters = [
                {"left": "type", "operation": "equal", "right": "stock"},
                {"left": "exchange", "operation": "in_range", "right": list(exchanges)},
        ]
        if symbols:
            filters.append({
                "left": "name", "operation": "in_range",
                "right": sorted({symbol.split(":", 1)[-1] for symbol in symbols}),
            })
        payload = {
            "filter": filters,
            "columns": list(columns),
            "sort": {"sortBy": "name", "sortOrder": "asc"},
            "range": [start, start + page_size],
        }
        response = _request_json(endpoint, payload, timeout)
        if not isinstance(response, dict) or type(response.get("totalCount")) is not int:
            raise TradingViewSourceError(f"{scanner}: malformed historical scanner response")
        count, page = response["totalCount"], response.get("data")
        if count == 0 and symbols:
            if page != []:
                raise TradingViewSourceError(f"{scanner}: malformed empty filtered scanner response")
            return []
        if count <= 0 or count > 100_000:
            raise TradingViewSourceError(f"{scanner}: invalid stock-universe count: {count}")
        if total is not None and count != total:
            raise TradingViewSourceError(f"{scanner}: stock universe changed during pagination")
        total = count
        if not isinstance(page, list) or len(page) != min(page_size, total - start):
            raise TradingViewSourceError(f"{scanner}: incomplete historical scanner page at offset {start}")
        for item in page:
            if not isinstance(item, dict) or not _text(item.get("s")):
                raise TradingViewSourceError(f"{scanner}: malformed historical symbol")
            symbol, values = item["s"], item.get("d")
            if symbol in seen:
                raise TradingViewSourceError(f"{scanner}: duplicate symbol across pages: {symbol}")
            if not isinstance(values, list) or len(values) != len(columns):
                raise TradingViewSourceError(f"{symbol}: incomplete historical scanner columns")
            row = dict(zip(columns, values), symbol=symbol)
            if row["exchange"] not in exchanges or row["type"] != "stock":
                raise TradingViewSourceError(f"{symbol}: scanner did not honor exchange/stock filters")
            if not _text(row["name"]) or symbol != f"{row['exchange']}:{row['name']}":
                raise TradingViewSourceError(f"{symbol}: inconsistent symbol identity")
            seen.add(symbol)
            rows.append(row)
    return rows


def historical_bar(row: dict[str, Any], offset: int, timezone_name: str) -> dict[str, Any] | None:
    values = {field: row.get(indexed(field, offset)) for field in BAR_COLUMNS}
    stamp = values["time"]
    if stamp is None:
        if all(values[field] is None for field in ("open", "high", "low", "close", "volume")):
            return None
        raise TradingViewSourceError(f"{row['symbol']}: historical price data has no bar timestamp")
    if not _number(stamp) or stamp <= 0:
        raise TradingViewSourceError(f"{row['symbol']}: invalid historical bar timestamp")
    try:
        day = datetime.fromtimestamp(stamp, timezone.utc).astimezone(ZoneInfo(timezone_name)).date()
    except (OverflowError, OSError, ValueError) as exc:
        raise TradingViewSourceError(f"{row['symbol']}: invalid historical bar timestamp") from exc
    return {**values, "date": day, "offset": offset}


def reports_from_rows(market_id: str, sessions: list[date], rows: list[dict[str, Any]],
                      max_offset: int, *, minimum_coverage: int,
                      collected_at: str | None = None) -> tuple[dict[date, dict], dict[date, dict]]:
    if market_id not in SUPPORTED_BACKFILL_MARKETS:
        raise TradingViewSourceError(f"Unsupported historical backfill market: {market_id}")
    if not sessions:
        raise ValueError("date range has no weekdays")
    if minimum_coverage < 1:
        raise ValueError("minimum_coverage must be positive")
    _scanner, exchanges = _CONFIG[market_id]
    if len(exchanges) != 1:
        raise TradingViewSourceError("historical backfill currently requires one configured exchange")
    timezone_name = next(iter(exchanges.values()))
    session_set = set(sessions)
    matched: dict[date, list[tuple[dict[str, Any], dict[str, Any]]]] = {
        session: [] for session in sessions
    }
    for row in rows:
        symbol_dates: set[date] = set()
        for offset in range(max_offset + 1):
            bar = historical_bar(row, offset, timezone_name)
            if bar is None or bar["date"] not in session_set:
                continue
            if bar["date"] in symbol_dates:
                raise TradingViewSourceError(f"{row['symbol']}: duplicate historical date {bar['date']}")
            symbol_dates.add(bar["date"])
            matched[bar["date"]].append((row, bar))
    for session, matches in matched.items():
        if len(matches) < minimum_coverage:
            raise TradingViewSourceError(
                f"{market_id} {session}: incomplete or non-trading session coverage "
                f"({len(matches)} symbols; require {minimum_coverage})"
            )

    collected_at = collected_at or datetime.now(timezone.utc).isoformat()
    reports: dict[date, dict] = {}
    reviews: dict[date, dict] = {}
    scanner = _CONFIG[market_id][0]
    for session in sessions:
        entries: list[dict[str, Any]] = []
        checks: list[dict[str, Any]] = []
        excluded_close = 0
        used_tickers: set[str] = set()
        for row, bar in matched[session]:
            candidate = {field: bar[field] for field in BAR_COLUMNS}
            high_type = _high_type(candidate)
            if high_type is None:
                continue
            passes_close = _passes_close_filter(candidate)
            check = {
                "ticker": row["name"], "source_symbol": row["symbol"],
                "date": session.isoformat(), "bar_offset": bar["offset"],
                "open": bar["open"], "daily_high": bar["high"], "low": bar["low"],
                "close": bar["close"], "volume": bar["volume"],
                "period_52_week_high": bar["price_52_week_high"],
                "period_all_time_high": bar["High.All"], "high_type": high_type,
                "passes_close_filter": passes_close, "included": passes_close,
            }
            checks.append(check)
            if not passes_close:
                excluded_close += 1
                continue
            exchange = row["exchange"]
            ticker = _ticker(row, exchange, market_id)
            if ticker.upper() in used_tickers:
                raise TradingViewSourceError(f"{market_id}: duplicate archive ticker: {ticker}")
            used_tickers.add(ticker.upper())
            if not _text(row["description"]):
                raise TradingViewSourceError(f"{row['symbol']}: missing company name")
            sector = row["sector"].strip() if _text(row["sector"]) else "미분류"
            industry = row["industry"].strip() if _text(row["industry"]) else "업종 정보 미확인"
            entries.append({
                "ticker": ticker, "name": row["description"], "exchange": exchange,
                "category": sector, "high_type": high_type, "reason": f"업종: {sector} · {industry}",
                "description": f"{row['description']} · {industry}", "change_pct": bar["change"],
                "session_open": bar["open"], "session_close": bar["close"],
                "source_symbol": row["symbol"],
                **({"currency": row["currency"].strip().upper()} if _text(row.get("currency")) else {}),
                "high_verification": {
                    "source": "TradingView historical screener fields",
                    "source_url": "https://www.tradingview.com/screener/",
                    **{key: value for key, value in check.items() if key not in {"ticker", "source_symbol", "included"}},
                },
            })
        entries.sort(key=lambda entry: (entry["exchange"], entry["ticker"]))
        checks.sort(key=lambda check: check["source_symbol"])
        coverage = len(matched[session])
        reports[session] = {
            "schema_version": 1, "market": market_id, "date": session.isoformat(),
            "summary": "과거 TradingView 일봉 기준. 당일 장중 고가가 52주·전체기간 고가에 도달하고, 음봉 또는 전일 대비 하락 마감이 아닌 종목입니다. 전체기간 신고가를 우선 표시하며 신고가 배경은 별도 확인 전입니다.",
            "sources": [
                {"label": "TradingView stock screener", "url": "https://www.tradingview.com/screener/"},
                {"label": "TradingView 신고가 산정 기준", "url": _DEFINITION_URL},
            ],
            "entries": entries,
            "source_metadata": {
                "provider": "TradingView historical screener fields",
                "universe_provider": "TradingView public scanner",
                "fetched_at": collected_at,
                "universe": "Current TradingView-listed stock instruments; ETFs and listings no longer in the current universe excluded",
                "definition": "daily high >= period high; close >= open; close >= previous close; all-time takes precedence; ties included",
                "scanner": scanner, "scanner_exchanges": list(exchanges),
                "scanned_symbols": len(rows), "session_symbols": coverage,
                "raw_new_high_candidates": len(checks),
                "excluded_bearish_or_down_close": excluded_close,
                "historical_offsets_checked": max_offset + 1,
                "pagination_complete": True,
            },
            "collected_at": collected_at,
        }
        reviews[session] = {
            "schema_version": 1, "market": market_id, "date": session.isoformat(),
            "reviewed_at": collected_at, "scanned_symbols": len(rows),
            "session_symbols": coverage, "checks": checks,
        }
    return reports, reviews


def build_reports(market_id: str, start: date, end: date, *, timeout: float = 30,
                  page_size: int = 500, max_lookback_sessions: int | None = None,
                  as_of: date | None = None) -> tuple[dict[date, dict], dict[date, dict]]:
    if market_id not in SUPPORTED_BACKFILL_MARKETS:
        raise TradingViewSourceError(f"Unsupported historical backfill market: {market_id}")
    sessions = requested_dates(start, end)
    if not sessions:
        raise ValueError("date range has no weekdays")
    timezone_name = next(iter(_CONFIG[market_id][1].values()))
    as_of = as_of or datetime.now(ZoneInfo(timezone_name)).date()
    max_offset = max_lookback_sessions if max_lookback_sessions is not None else default_max_offset(start, as_of)
    rows = scan_historical(market_id, max_offset, timeout, page_size)
    minimum_coverage = max(1000, math.ceil(len(rows) * 0.5))
    return reports_from_rows(
        market_id, sessions, rows, max_offset,
        minimum_coverage=minimum_coverage,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--market", choices=sorted(SUPPORTED_BACKFILL_MARKETS), default="japan")
    parser.add_argument("--start", required=True, type=date.fromisoformat)
    parser.add_argument("--end", required=True, type=date.fromisoformat)
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--page-size", type=int, default=500)
    parser.add_argument("--max-lookback-sessions", type=int)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--source-dir", type=Path, default=SOURCE_DIR)
    args = parser.parse_args()
    if args.max_lookback_sessions is not None and not 0 <= args.max_lookback_sessions <= 260:
        parser.error("--max-lookback-sessions must be between 0 and 260")
    try:
        reports, reviews = build_reports(
            args.market, args.start, args.end, timeout=args.timeout, page_size=args.page_size,
            max_lookback_sessions=args.max_lookback_sessions,
        )
        markets = {market["id"]: market for market in load_markets(args.source_dir)}
        reports_dir = args.source_dir / "reports"
        for session, report in reports.items():
            report_path = reports_dir / args.market / f"{session}.json"
            if report_path.exists() and not args.force:
                parser.error(f"report already exists: {report_path}; use --force to replace it")
            validate_report(report, report_path, reports_dir, markets)
    except (TradingViewSourceError, ValueError) as exc:
        parser.exit(1, f"Historical new-high backfill failed: {exc}\n")
    for session, report in reports.items():
        atomic_json(args.source_dir / "reports" / args.market / f"{session}.json", report)
        atomic_json(args.source_dir / "reviews" / args.market / f"{session}.json", reviews[session])
        print(f"{args.market} {session}: {len(report['entries'])} entries")


if __name__ == "__main__":
    main()
