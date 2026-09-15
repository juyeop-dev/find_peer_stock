"""Fetch a complete latest-session stock snapshot from TradingView's public scanner.

The scanner is an undocumented public endpoint, not a historical archive or an
exchange-wide data guarantee. Fail closed if its response, coverage, or session
changes. The caller decides when exchanges have closed and persists each report.

Definition: https://www.tradingview.com/support/solutions/43000753745/
The daily high must equal or exceed the period high. This archive additionally
requires close >= open and close >= previous close; all-time takes precedence.
"""

from __future__ import annotations

import ast
import json
import math
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


class TradingViewSourceError(ValueError):
    """The source cannot prove a complete, correctly classified report."""


class TradingViewSourceNotReady(TradingViewSourceError):
    """A requested trading session is not the latest available source session."""


SUPPORTED_MARKETS = frozenset({"korea", "us", "taiwan", "japan", "europe"})
_CONFIG = {
    "korea": ("korea", {"KRX": "Asia/Seoul"}),
    "us": ("america", {"NASDAQ": "America/New_York", "NYSE": "America/New_York", "AMEX": "America/New_York"}),
    "taiwan": ("taiwan", {"TWSE": "Asia/Taipei", "TPEX": "Asia/Taipei"}),
    "japan": ("japan", {"TSE": "Asia/Tokyo"}),
    "europe": ("global", {"EURONEXT": "Europe/Paris", "XETR": "Europe/Berlin", "LSE": "Europe/London", "SIX": "Europe/Zurich"}),
}
COLUMNS = (
    "name", "description", "exchange", "type", "subtype", "sector", "industry",
    "change", "open", "high", "low", "close", "price_52_week_high", "High.All", "time", "volume", "indexes",
    "currency",
)
_DEFINITION_URL = "https://www.tradingview.com/support/solutions/43000753745-how-are-high-low-and-new-high-new-low-calculated/"


def _request_json(url: str, payload: dict[str, Any] | None, timeout: float) -> Any:
    request = Request(
        url,
        data=json.dumps(payload, allow_nan=False).encode("utf-8") if payload is not None else None,
        headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0", "Accept": "application/json"},
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
        raise TradingViewSourceError(f"Cannot read {url}: {exc}") from exc


def _number(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _scan(market_id: str, timeout: float, page_size: int) -> list[dict[str, Any]]:
    scanner, exchanges = _CONFIG[market_id]
    endpoint = f"https://scanner.tradingview.com/{scanner}/scan"
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    total: int | None = None
    while total is None or len(rows) < total:
        offset = len(rows)
        payload = {
            "filter": [
                {"left": "type", "operation": "equal", "right": "stock"},
                {"left": "exchange", "operation": "in_range", "right": list(exchanges)},
            ],
            "columns": list(COLUMNS),
            "sort": {"sortBy": "name", "sortOrder": "asc"},
            "range": [offset, offset + page_size],
        }
        response = _request_json(endpoint, payload, timeout)
        if not isinstance(response, dict) or type(response.get("totalCount")) is not int:
            raise TradingViewSourceError(f"{scanner}: malformed scanner response")
        count, page = response["totalCount"], response.get("data")
        if count <= 0 or count > 100_000:
            raise TradingViewSourceError(f"{scanner}: invalid stock-universe count: {count}")
        if total is not None and count != total:
            raise TradingViewSourceError(f"{scanner}: stock universe changed during pagination")
        total = count
        if not isinstance(page, list) or len(page) != min(page_size, total - offset):
            raise TradingViewSourceError(f"{scanner}: incomplete scanner page at offset {offset}")
        for item in page:
            if not isinstance(item, dict) or not _text(item.get("s")):
                raise TradingViewSourceError(f"{scanner}: malformed symbol")
            symbol, values = item["s"], item.get("d")
            if symbol in seen:
                raise TradingViewSourceError(f"{scanner}: duplicate symbol across pages: {symbol}")
            if not isinstance(values, list) or len(values) != len(COLUMNS):
                raise TradingViewSourceError(f"{symbol}: incomplete scanner columns")
            row = dict(zip(COLUMNS, values), symbol=symbol)
            if row["exchange"] not in exchanges or row["type"] != "stock":
                raise TradingViewSourceError(f"{symbol}: scanner did not honor exchange/stock filters")
            if not _text(row["name"]) or symbol != f"{row['exchange']}:{row['name']}":
                raise TradingViewSourceError(f"{symbol}: inconsistent symbol identity")
            seen.add(symbol)
            rows.append(row)
    return rows


def _bar_date(row: dict[str, Any], timezone_name: str) -> date | None:
    value = row["time"]
    if value is None:
        # A listing with no price history is not an observed trading session.
        if all(row[field] is None for field in ("high", "price_52_week_high", "High.All", "volume")):
            return None
        raise TradingViewSourceError(f"{row['symbol']}: price data has no daily bar date")
    if not _number(value) or value <= 0:
        raise TradingViewSourceError(f"{row['symbol']}: invalid daily bar timestamp")
    try:
        return datetime.fromtimestamp(value, timezone.utc).astimezone(ZoneInfo(timezone_name)).date()
    except (OverflowError, OSError, ValueError) as exc:
        raise TradingViewSourceError(f"{row['symbol']}: invalid daily bar timestamp") from exc


def _korean_index_board(row: dict[str, Any]) -> str | None:
    indexes = row["indexes"]
    if indexes is None:
        return None
    if not isinstance(indexes, list) or any(not isinstance(index, dict) for index in indexes):
        raise TradingViewSourceError(f"{row['symbol']}: malformed index membership")
    names = {index.get("proname") for index in indexes}
    matches = {board for board in ("KOSPI", "KOSDAQ") if f"KRX:{board}" in names}
    if len(matches) > 1:
        raise TradingViewSourceError(f"{row['symbol']}: contradictory Korean board membership")
    return next(iter(matches), None)


def fetch_korean_listing(code: str, timeout: float = 30) -> dict[str, str]:
    """Resolve Naver's Korean display name by stock code, never translation."""
    url = f"https://m.stock.naver.com/api/stock/{quote(code, safe='')}/basic"
    data = _request_json(url, None, timeout)
    if not isinstance(data, dict) or data.get("itemCode") != code:
        raise TradingViewSourceError(f"KRX:{code}: could not verify Korean listing")
    exchange = data.get("stockExchangeType")
    board = exchange.get("name") if isinstance(exchange, dict) else None
    if board not in {"KOSPI", "KOSDAQ"}:
        raise TradingViewSourceError(f"KRX:{code}: unsupported or missing Korean board: {board}")
    if not _text(data.get("stockName")):
        raise TradingViewSourceError(f"KRX:{code}: missing Korean listing name")
    return {"name": data["stockName"].strip(), "exchange": board, "source_url": url}


def _request_daily_history(url: str, timeout: float) -> list:
    request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = ast.literal_eval(response.read().decode("utf-8-sig").strip())
        if not isinstance(payload, list) or not payload:
            raise ValueError("missing daily history")
        return payload[1:]
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, SyntaxError) as exc:
        raise TradingViewSourceError(f"Cannot read Korean daily history: {exc}") from exc


def verify_korean_daily_high(code: str, session_date: date, timeout: float = 30) -> dict[str, Any]:
    """Veto scanner candidates contradicted by the dated, adjusted daily bars.

    This is an independent check of candidates, not a replacement universe scan
    or proof of all-time history. Newly listed stocks use their available bars.
    """
    start = session_date - timedelta(weeks=52)
    url = "https://api.finance.naver.com/siseJson.naver?" + urlencode({
        "symbol": code, "requestType": "1", "startTime": start.strftime("%Y%m%d"),
        "endTime": session_date.strftime("%Y%m%d"), "timeframe": "day",
    })
    rows = _request_daily_history(url, timeout)
    previous_highs = []
    previous_closes: list[tuple[date, float | int]] = []
    current = None
    seen = set()
    for row in rows:
        if not isinstance(row, list) or len(row) < 6:
            raise TradingViewSourceError(f"KRX:{code}: malformed daily history")
        try:
            day = datetime.strptime(str(row[0]), "%Y%m%d").date()
        except ValueError as exc:
            raise TradingViewSourceError(f"KRX:{code}: invalid daily history date") from exc
        if day in seen or not start <= day <= session_date:
            raise TradingViewSourceError(f"KRX:{code}: duplicate or unexpected daily history date")
        seen.add(day)
        if not _number(row[2]) or row[2] < 0 or not _number(row[4]) or row[4] <= 0 or \
                not _number(row[5]) or row[5] < 0:
            raise TradingViewSourceError(f"KRX:{code}: invalid daily high, close or volume")
        if day == session_date:
            if any(not _number(row[index]) or row[index] <= 0 for index in (1, 3)):
                raise TradingViewSourceError(f"KRX:{code}: invalid current-session open or low")
            current = row
        else:
            if row[2] > 0:
                previous_highs.append(row[2])
            previous_closes.append((day, row[4]))
    if current is None:
        raise TradingViewSourceNotReady(f"KRX:{code}: daily history has no {session_date} bar")
    prior_high = max(previous_highs, default=None)
    previous_close = max(previous_closes, default=(None, None), key=lambda item: item[0])[1]
    bearish_candle = current[4] < current[1]
    down_close = previous_close is not None and current[4] < previous_close
    confirmed = current[2] > 0 and current[5] > 0 and (prior_high is None or current[2] >= prior_high)
    return {
        "source": "Naver Finance adjusted daily history", "source_url": url,
        "date": session_date.isoformat(), "open": current[1], "daily_high": current[2],
        "low": current[3], "close": current[4], "previous_close": previous_close, "volume": current[5],
        "prior_52_week_high": prior_high, "observed_bars": len(rows),
        "first_observed_date": min(seen).isoformat(), "confirmed": confirmed,
        "matches_prior_high": prior_high is not None and current[2] == prior_high,
        "bearish_candle": bearish_candle, "down_close": down_close,
        "passes_close_filter": not bearish_candle and not down_close,
    }


def _passes_close_filter(row: dict[str, Any]) -> bool:
    for field in ("open", "close", "change"):
        if not _number(row[field]):
            raise TradingViewSourceError(f"{row['symbol']}: missing OHLC/change prevents close-direction filtering")
    if row["open"] <= 0 or row["close"] <= 0:
        raise TradingViewSourceError(f"{row['symbol']}: invalid open or close")
    return row["close"] >= row["open"] and row["change"] >= 0


def _high_type(row: dict[str, Any]) -> str | None:
    high, week, lifetime = row["high"], row["price_52_week_high"], row["High.All"]
    for name, value in (("high", high), ("price_52_week_high", week), ("High.All", lifetime)):
        if value is not None and (not _number(value) or value <= 0):
            raise TradingViewSourceError(f"{row['symbol']}: invalid {name}")
    if high is None:
        raise TradingViewSourceError(f"{row['symbol']}: latest session has no daily high")
    if lifetime is not None and high >= lifetime:
        return "all_time"
    if week is not None:
        if high < week:
            return None
        if lifetime is not None:
            return "52_week"
    # Never turn a missing lookback value into a negative result, including zero days.
    raise TradingViewSourceError(f"{row['symbol']}: missing history prevents new-high classification")


def _ticker(row: dict[str, Any], exchange: str, market_id: str) -> str:
    suffixes = {"KOSPI": ".KS", "KOSDAQ": ".KQ", "TWSE": ".TW", "TPEX": ".TWO", "TSE": ".T"}
    if exchange in suffixes:
        return row["name"] + suffixes[exchange]
    return row["name"] if market_id == "us" else row["symbol"]


def fetch_report(market_id: str, session_date: date, *, timeout: float = 30,
                 page_size: int = 500) -> dict[str, Any]:
    """Return a report only when every configured source exchange has the target bar date.

    Suspended/no-trade symbols with an older last bar are explicitly excluded;
    an entirely stale exchange is not a confirmed zero. Historical backfills are
    impossible with this endpoint and raise TradingViewSourceNotReady.
    """
    if market_id not in SUPPORTED_MARKETS:
        detail = ": TradingView does not cover the configured Beijing exchange (BSE)" if market_id == "china" else ""
        raise TradingViewSourceError(f"Unsupported automatic new-high market: {market_id}{detail}")
    if type(session_date) is not date:
        raise TradingViewSourceError("session_date must be a datetime.date")
    if type(page_size) is not int or not 1 <= page_size <= 5000:
        raise TradingViewSourceError("page_size must be an integer between 1 and 5000")
    if not _number(timeout) or timeout <= 0:
        raise TradingViewSourceError("timeout must be positive and finite")
    scanner, exchanges = _CONFIG[market_id]
    rows = _scan(market_id, timeout, page_size)
    latest: dict[str, date] = {}
    references: dict[str, str] = {}
    current: list[dict[str, Any]] = []
    excluded = Counter()
    for row in rows:
        day = _bar_date(row, exchanges[row["exchange"]])
        if day is None:
            excluded["no_price_history"] += 1
            continue
        exchange = row["exchange"]
        latest[exchange] = max(day, latest.get(exchange, day))
        if day != session_date:
            excluded["other_session"] += 1
            continue
        current.append(row)
        references.setdefault(exchange, row["symbol"])
        if market_id == "korea":
            board = _korean_index_board(row)
            if board:
                references.setdefault(board, row["symbol"])
    for exchange in exchanges:
        if exchange not in latest:
            raise TradingViewSourceError(f"{market_id}: no dated stocks for required exchange {exchange}")
        if latest[exchange] != session_date:
            raise TradingViewSourceNotReady(
                f"{market_id}/{exchange}: source session is {latest[exchange]}, requested {session_date}"
            )
    if market_id == "korea" and not {"KOSPI", "KOSDAQ"}.issubset(references):
        raise TradingViewSourceError("korea: cannot verify current-session coverage of both KOSPI and KOSDAQ")
    entries = []
    used_tickers: set[str] = set()
    for row in current:
        high_type = _high_type(row)
        if high_type is None:
            continue
        listing = fetch_korean_listing(row["name"], timeout) if market_id == "korea" else None
        exchange = listing["exchange"] if listing else row["exchange"]
        if listing and _korean_index_board(row) not in {None, exchange}:
            raise TradingViewSourceError(f"{row['symbol']}: conflicting Korean listing exchange")
        evidence = verify_korean_daily_high(row["name"], session_date, timeout) if listing else None
        if evidence and not evidence["confirmed"]:
            excluded["korean_daily_history_disagrees"] += 1
            continue
        if evidence is not None:
            if not evidence["passes_close_filter"]:
                excluded["bearish_or_down_close"] += 1
                continue
        elif not _passes_close_filter(row):
            excluded["bearish_or_down_close"] += 1
            continue
        exchange = "XETRA" if exchange == "XETR" else exchange
        ticker = _ticker(row, exchange, market_id)
        if ticker.upper() in used_tickers:
            raise TradingViewSourceError(f"{market_id}: duplicate archive ticker: {ticker}")
        used_tickers.add(ticker.upper())
        if not _text(row["description"]):
            raise TradingViewSourceError(f"{row['symbol']}: missing company name")
        if row["change"] is not None and not _number(row["change"]):
            raise TradingViewSourceError(f"{row['symbol']}: invalid price change")
        sector = row["sector"].strip() if _text(row["sector"]) else "미분류"
        industry = row["industry"].strip() if _text(row["industry"]) else "업종 정보 미확인"
        display_name = listing["name"] if listing else row["description"]
        entries.append({
            "ticker": ticker, "name": display_name, "exchange": exchange,
            "category": sector, "high_type": high_type, "reason": f"업종: {sector} · {industry}",
            "description": f"{display_name} · {industry}", "change_pct": row["change"],
            "session_open": evidence["open"] if evidence else row["open"],
            "session_close": evidence["close"] if evidence else row["close"],
            "source_symbol": row["symbol"],
            **({"currency": row["currency"].strip().upper()} if _text(row["currency"]) else {}),
            **({"name_original": row["description"], "name_source_url": listing["source_url"],
                "high_verification": evidence} if listing else {}),
        })
    entries.sort(key=lambda entry: (entry["exchange"], entry["ticker"]))
    return {
        "schema_version": 1, "market": market_id, "date": session_date.isoformat(),
        "summary": "장 마감 후 TradingView 주식 스냅샷 기준. 당일 장중 고가가 52주·전체기간 고가에 도달하고, 음봉 또는 전일 대비 하락 마감이 아닌 종목입니다. 전체기간 신고가를 우선 표시하며 신고가 배경은 별도 확인 전입니다.",
        "sources": [
            {"label": "TradingView stock screener", "url": "https://www.tradingview.com/screener/"},
            {"label": "TradingView 신고가 산정 기준", "url": _DEFINITION_URL},
        ] + ([{"label": "Naver Finance 종목명·상장 시장·일봉 검증", "url": "https://stock.naver.com/"}] if market_id == "korea" else []),
        "entries": entries,
        "source_metadata": {
            "provider": "TradingView public scanner", "scanner": scanner,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "universe": "TradingView-listed stock instruments, including common and preferred shares; ETFs excluded",
            "definition": "daily high >= period high; close >= open; close >= previous close; all-time takes precedence; ties included",
            "scanner_exchanges": list(exchanges),
            "latest_session_by_exchange": {exchange: day.isoformat() for exchange, day in latest.items()},
            "current_session_reference_symbols": references,
            "scanned_symbols": len(rows), "current_session_symbols": len(current),
            "excluded_symbols": dict(excluded), "pagination_complete": True,
        },
    }
