from __future__ import annotations

import json
import math
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class MarketDataError(RuntimeError):
    pass


@dataclass(frozen=True)
class Quote:
    ticker: str
    price: float
    previous_close: float | None
    change: float | None
    change_pct: float | None
    currency: str
    timestamp: datetime | None
    basis_label: str | None = None


def fetch_latest_quote(ticker: str, *, include_prepost: bool = False) -> Quote:
    params = urllib.parse.urlencode(
        {
            "range": "1d",
            "interval": "1m",
            "includePrePost": str(include_prepost).lower(),
        }
    )
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?{params}"
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 telegram-scheduled-bot",
            "Accept": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise MarketDataError(f"{ticker}: HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise MarketDataError(f"{ticker}: network error: {exc.reason}") from exc

    result = _first_chart_result(payload, ticker)
    meta = result.get("meta", {})
    timestamps = result.get("timestamp") or []
    quote_rows = (
        result.get("indicators", {})
        .get("quote", [{}])[0]
    )
    closes = quote_rows.get("close") or []

    latest = _select_latest_quote(meta, timestamps, closes)
    if latest is None:
        raise MarketDataError(f"{ticker}: no latest price in Yahoo chart data")

    latest_price, latest_time = latest

    previous_close = _as_float(meta.get("chartPreviousClose"))
    change = None
    change_pct = None
    if previous_close and previous_close > 0:
        change = latest_price - previous_close
        change_pct = (latest_price / previous_close - 1) * 100

    return Quote(
        ticker=ticker,
        price=latest_price,
        previous_close=previous_close,
        change=change,
        change_pct=change_pct,
        currency=str(meta.get("currency") or "JPY"),
        timestamp=latest_time,
    )


def _first_chart_result(payload: dict[str, Any], ticker: str) -> dict[str, Any]:
    chart = payload.get("chart", {})
    error = chart.get("error")
    if error:
        description = error.get("description") or error
        raise MarketDataError(f"{ticker}: {description}")

    results = chart.get("result") or []
    if not results:
        raise MarketDataError(f"{ticker}: empty Yahoo chart response")
    return results[0]


def _latest_numeric_index(values: list[Any]) -> int | None:
    for index in range(len(values) - 1, -1, -1):
        value = _as_float(values[index])
        if value is not None:
            return index
    return None


def _select_latest_quote(
    meta: dict[str, Any],
    timestamps: list[Any],
    closes: list[Any],
) -> tuple[float, datetime | None] | None:
    timezone = _market_timezone(meta)
    meta_price = _as_float(meta.get("regularMarketPrice"))
    meta_time = _timestamp_to_datetime(meta.get("regularMarketTime"), timezone)

    latest_index = _latest_numeric_index(closes)
    if latest_index is None:
        if meta_price is None:
            return None
        return meta_price, meta_time

    bar_price = float(closes[latest_index])
    bar_time = (
        _timestamp_to_datetime(timestamps[latest_index], timezone)
        if latest_index < len(timestamps)
        else None
    )

    if meta_price is not None and _is_meta_quote_at_least_as_fresh(meta_time, bar_time):
        return meta_price, meta_time
    return bar_price, bar_time


def _is_meta_quote_at_least_as_fresh(meta_time: datetime | None, bar_time: datetime | None) -> bool:
    if meta_time is None:
        return bar_time is None
    if bar_time is None:
        return True
    return meta_time >= bar_time


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def _market_timezone(meta: dict[str, Any]) -> ZoneInfo:
    timezone_name = meta.get("exchangeTimezoneName")
    if isinstance(timezone_name, str) and timezone_name:
        try:
            return ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            pass
    return ZoneInfo("UTC")


def _timestamp_to_datetime(value: Any, timezone: ZoneInfo) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=timezone)
    except (TypeError, ValueError, OSError):
        return None
