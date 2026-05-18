from __future__ import annotations

import json
import math
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from yahoo_chart import MarketDataError, Quote


TPE = ZoneInfo("Asia/Taipei")
TWSE_STOCK_DAY_URL = "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY"
TWSE_SSL_CONTEXT = ssl._create_unverified_context()


class TaiwanQuoteUnavailable(MarketDataError):
    pass


def is_taiwan_ticker(ticker: str) -> bool:
    return ticker.upper().endswith(".TW")


def fetch_taiwan_quote(ticker: str) -> Quote:
    code = _extract_taiwan_code(ticker)
    today = datetime.now(tz=TPE)

    try:
        return _fetch_twse_stock_day_quote(ticker, code, today)
    except TaiwanQuoteUnavailable as current_month_error:
        try:
            return _fetch_twse_stock_day_quote(ticker, code, _previous_month(today))
        except MarketDataError as previous_month_error:
            raise MarketDataError(
                f"{ticker}: TWSE daily quote failed: {current_month_error}; {previous_month_error}"
            ) from previous_month_error


def _extract_taiwan_code(ticker: str) -> str:
    code = ticker.split(".", 1)[0]
    if not re.fullmatch(r"\d{4}", code):
        raise MarketDataError(f"{ticker}: expected a four-digit Taiwan stock code")
    return code


def _fetch_twse_stock_day_quote(ticker: str, code: str, query_month: datetime) -> Quote:
    params = urllib.parse.urlencode(
        {
            "date": f"{query_month:%Y%m}01",
            "stockNo": code,
            "response": "json",
        }
    )
    request = urllib.request.Request(
        f"{TWSE_STOCK_DAY_URL}?{params}",
        headers={
            "User-Agent": "Mozilla/5.0 telegram-scheduled-bot",
            "Accept": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=30, context=TWSE_SSL_CONTEXT) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise MarketDataError(f"{ticker}: TWSE HTTP {exc.code}: {body[:200]}") from exc
    except urllib.error.URLError as exc:
        raise MarketDataError(f"{ticker}: TWSE network error: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise MarketDataError(f"{ticker}: TWSE JSON decode error: {exc}") from exc

    rows = payload.get("data") or []
    if payload.get("stat") != "OK" or not rows:
        stat = payload.get("stat") or "empty response"
        raise TaiwanQuoteUnavailable(f"{ticker}: TWSE {stat}")

    fields = {name: index for index, name in enumerate(payload.get("fields") or [])}
    latest = _select_quote_row(rows)
    close = _parse_number(latest[fields["收盤價"]])
    change = _parse_number(latest[fields["漲跌價差"]])
    previous_close = close - change
    change_pct = (change / previous_close * 100) if previous_close else None
    timestamp = _parse_roc_date(latest[fields["日期"]])

    return Quote(
        ticker=ticker,
        price=close,
        previous_close=previous_close,
        change=change,
        change_pct=change_pct,
        currency="TWD",
        timestamp=timestamp,
        basis_label=None,
    )


def _select_quote_row(rows: list[list[Any]]) -> list[Any]:
    return rows[-1]


def _previous_month(value: datetime) -> datetime:
    if value.month == 1:
        return value.replace(year=value.year - 1, month=12, day=1)
    return value.replace(month=value.month - 1, day=1)


def _parse_roc_date(value: str) -> datetime:
    year_text, month_text, day_text = value.split("/")
    year = int(year_text) + 1911
    return datetime(year, int(month_text), int(day_text), 13, 30, tzinfo=TPE)


def _parse_number(value: Any) -> float:
    text = str(value).replace(",", "").strip()
    if text in {"", "--", "-"}:
        raise ValueError(f"not a number: {value!r}")
    number = float(text)
    if math.isnan(number) or math.isinf(number):
        raise ValueError(f"not a finite number: {value!r}")
    return number
