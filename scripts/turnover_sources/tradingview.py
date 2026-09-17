"""Collect the latest completed-session stock turnover top 30 from TradingView."""

from __future__ import annotations

import json
import math
from datetime import date, datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


class TurnoverSourceError(ValueError):
    """The source cannot provide a complete, correctly dated ranking."""


class TurnoverSourceNotReady(TurnoverSourceError):
    """The requested session is not the source's latest completed session."""


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
    "close", "change", "Value.Traded", "market_cap_basic", "currency", "time", "indexes", "logoid",
)


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
        raise TurnoverSourceError(f"Cannot read {url}: {exc}") from exc


def _number(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _bar_date(row: dict[str, Any], timezone_name: str) -> date | None:
    value = row["time"]
    if value is None and row["close"] is None and row["Value.Traded"] is None:
        return None
    if not _number(value) or value <= 0:
        raise TurnoverSourceError(f"{row['symbol']}: invalid daily bar timestamp")
    try:
        return datetime.fromtimestamp(value, timezone.utc).astimezone(ZoneInfo(timezone_name)).date()
    except (OverflowError, OSError, ValueError) as exc:
        raise TurnoverSourceError(f"{row['symbol']}: invalid daily bar timestamp") from exc


def _korean_board(row: dict[str, Any]) -> str | None:
    indexes = row["indexes"]
    if indexes is None:
        return None
    if not isinstance(indexes, list) or any(not isinstance(index, dict) for index in indexes):
        raise TurnoverSourceError(f"{row['symbol']}: malformed index membership")
    names = {index.get("proname") for index in indexes}
    matches = {board for board in ("KOSPI", "KOSDAQ") if f"KRX:{board}" in names}
    if len(matches) > 1:
        raise TurnoverSourceError(f"{row['symbol']}: contradictory Korean board membership")
    return next(iter(matches), None)


def _korean_listing(code: str, timeout: float) -> dict[str, str]:
    url = f"https://m.stock.naver.com/api/stock/{quote(code, safe='')}/basic"
    data = _request_json(url, None, timeout)
    exchange = data.get("stockExchangeType") if isinstance(data, dict) else None
    board = exchange.get("name") if isinstance(exchange, dict) else None
    if not isinstance(data, dict) or data.get("itemCode") != code or board not in {"KOSPI", "KOSDAQ"}:
        raise TurnoverSourceError(f"KRX:{code}: could not verify Korean listing")
    if not _text(data.get("stockName")):
        raise TurnoverSourceError(f"KRX:{code}: missing Korean listing name")
    return {"name": data["stockName"].strip(), "exchange": board}


def _ticker(code: str, exchange: str, market_id: str, symbol: str) -> str:
    suffixes = {"KOSPI": ".KS", "KOSDAQ": ".KQ", "TWSE": ".TW", "TPEX": ".TWO", "TSE": ".T"}
    if exchange in suffixes:
        return code + suffixes[exchange]
    return code if market_id == "us" else symbol


def _logo_url(logoid: Any) -> str | None:
    if not _text(logoid):
        return None
    clean = logoid.strip()
    if any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_/" for char in clean):
        return None
    return f"https://s3-symbol-logo.tradingview.com/{clean}--big.svg"


def fetch_report(market_id: str, session_date: date, *, timeout: float = 30,
                 page_size: int = 1000, limit: int = 30) -> dict[str, Any]:
    if market_id not in SUPPORTED_MARKETS:
        raise TurnoverSourceError(f"Unsupported automatic turnover market: {market_id}")
    if type(session_date) is not date:
        raise TurnoverSourceError("session_date must be a datetime.date")
    if type(limit) is not int or not 1 <= limit <= 30:
        raise TurnoverSourceError("limit must be an integer between 1 and 30")
    if type(page_size) is not int or not 1 <= page_size <= 5000:
        raise TurnoverSourceError("page_size must be an integer between 1 and 5000")
    if not _number(timeout) or timeout <= 0:
        raise TurnoverSourceError("timeout must be positive and finite")

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
            "sort": {"sortBy": "Value.Traded", "sortOrder": "desc"},
            "range": [offset, offset + page_size],
        }
        response = _request_json(endpoint, payload, timeout)
        if not isinstance(response, dict) or type(response.get("totalCount")) is not int:
            raise TurnoverSourceError(f"{scanner}: malformed scanner response")
        count, page = response["totalCount"], response.get("data")
        if count <= 0 or count > 100_000:
            raise TurnoverSourceError(f"{scanner}: invalid stock-universe count: {count}")
        if total is not None and count != total:
            raise TurnoverSourceError(f"{scanner}: stock universe changed during pagination")
        total = count
        if not isinstance(page, list) or len(page) != min(page_size, total - offset):
            raise TurnoverSourceError(f"{scanner}: incomplete scanner page at offset {offset}")
        for item in page:
            if not isinstance(item, dict) or not _text(item.get("s")):
                raise TurnoverSourceError(f"{scanner}: malformed symbol")
            symbol, values = item["s"], item.get("d")
            if symbol in seen or not isinstance(values, list) or len(values) != len(COLUMNS):
                raise TurnoverSourceError(f"{symbol}: duplicate or incomplete scanner row")
            row = dict(zip(COLUMNS, values), symbol=symbol)
            if row["exchange"] not in exchanges or row["type"] != "stock":
                raise TurnoverSourceError(f"{symbol}: scanner did not honor filters")
            seen.add(symbol)
            rows.append(row)

    latest: dict[str, date] = {}
    current: list[dict[str, Any]] = []
    for row in rows:
        day = _bar_date(row, exchanges[row["exchange"]])
        if day is None:
            continue
        latest[row["exchange"]] = max(day, latest.get(row["exchange"], day))
        if day == session_date:
            current.append(row)
    for exchange in exchanges:
        if latest.get(exchange) != session_date:
            actual = latest.get(exchange)
            raise TurnoverSourceNotReady(
                f"{market_id}/{exchange}: source session is {actual}, requested {session_date}"
            )

    ranked = []
    for row in current:
        turnover, price, change, market_cap = (
            row["Value.Traded"], row["close"], row["change"], row["market_cap_basic"]
        )
        if turnover is None:
            continue
        if not _number(turnover) or turnover < 0 or not _number(price) or price <= 0:
            raise TurnoverSourceError(f"{row['symbol']}: invalid turnover or close")
        if change is not None and not _number(change):
            raise TurnoverSourceError(f"{row['symbol']}: invalid change")
        if market_cap is not None and (not _number(market_cap) or market_cap <= 0):
            raise TurnoverSourceError(f"{row['symbol']}: invalid market cap")
        ranked.append(row)
    ranked.sort(key=lambda row: (-row["Value.Traded"], row["symbol"]))
    ranked = ranked[:limit]

    entries = []
    for rank, row in enumerate(ranked, start=1):
        price, change, turnover, market_cap = (
            row["close"], row["change"], row["Value.Traded"], row["market_cap_basic"]
        )
        listing = _korean_listing(row["name"], timeout) if market_id == "korea" else None
        exchange = listing["exchange"] if listing else row["exchange"]
        if listing and _korean_board(row) not in {None, exchange}:
            raise TurnoverSourceError(f"{row['symbol']}: conflicting Korean listing exchange")
        exchange = "XETRA" if exchange == "XETR" else exchange
        display_name = listing["name"] if listing else row["description"]
        if not _text(display_name):
            raise TurnoverSourceError(f"{row['symbol']}: missing company name")
        currency = row["currency"].strip().upper() if _text(row["currency"]) else None
        if currency is None or len(currency) != 3:
            raise TurnoverSourceError(f"{row['symbol']}: invalid currency")
        entries.append({
            "rank": rank,
            "ticker": _ticker(row["name"], exchange, market_id, row["symbol"]),
            "name": display_name,
            "exchange": exchange,
            "price": price,
            "change_pct": change,
            "turnover": turnover,
            "currency": currency,
            "market_cap": market_cap,
            "sector": row["sector"].strip() if _text(row["sector"]) else "미분류",
            "industry": row["industry"].strip() if _text(row["industry"]) else "업종 정보 미확인",
            "source_symbol": row["symbol"],
            **({"logo_url": logo} if (logo := _logo_url(row["logoid"])) else {}),
        })

    return {
        "schema_version": 1,
        "market": market_id,
        "date": session_date.isoformat(),
        "summary": "장 마감 후 TradingView 주식 스크리너의 당일 Turnover 기준 상위 30개 종목입니다.",
        "sources": [{"label": "TradingView Stock Screener", "url": "https://www.tradingview.com/screener/"}],
        "entries": entries,
        "source_metadata": {
            "provider": "TradingView public scanner",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "ranking": "Value.Traded descending; stocks only; ETFs excluded",
            "scanned_symbols": len(rows),
            "current_session_symbols": len(current),
            "latest_session_by_exchange": {key: value.isoformat() for key, value in latest.items()},
        },
    }
