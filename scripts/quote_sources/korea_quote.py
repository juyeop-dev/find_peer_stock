from __future__ import annotations

import html as html_lib
import json
import math
import re
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from yahoo_chart import MarketDataError, Quote


KST = ZoneInfo("Asia/Seoul")
KOREAN_TICKER_SUFFIXES = (".KS", ".KQ")
NAVER_FINANCE_URL = "https://finance.naver.com/item/sise.naver?code={code}"
TRADINGVIEW_SCAN_URL = "https://scanner.tradingview.com/korea/scan"


def is_korean_ticker(ticker: str) -> bool:
    return ticker.upper().endswith(KOREAN_TICKER_SUFFIXES)


def fetch_korean_quote(ticker: str) -> Quote:
    code = _extract_korean_code(ticker)
    errors = []

    for fetcher in (_fetch_naver_finance_quote, _fetch_tradingview_quote):
        try:
            return fetcher(ticker, code)
        except MarketDataError as exc:
            errors.append(str(exc))

    raise MarketDataError(f"{ticker}: Korean quote sources failed: {'; '.join(errors)}")


def _extract_korean_code(ticker: str) -> str:
    code = ticker.split(".", 1)[0]
    if not re.fullmatch(r"\d{6}", code):
        raise MarketDataError(f"{ticker}: expected a six-digit Korean stock code")
    return code


def _fetch_naver_finance_quote(ticker: str, code: str) -> Quote:
    url = NAVER_FINANCE_URL.format(code=code)
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 telegram-scheduled-bot",
            "Referer": "https://finance.naver.com/",
            "Accept": "text/html,application/xhtml+xml",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            charset = response.headers.get_content_charset() or "euc-kr"
            page = response.read().decode(charset, errors="replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise MarketDataError(f"{ticker}: Naver Finance HTTP {exc.code}: {body[:200]}") from exc
    except urllib.error.URLError as exc:
        raise MarketDataError(f"{ticker}: Naver Finance network error: {exc.reason}") from exc

    quote_text = _extract_naver_quote_text(page, code, ticker)
    timestamp = _parse_naver_timestamp(quote_text)
    basis_label = _parse_naver_basis_label(page)
    price = _parse_required_number(r"현재가\s*([0-9,]+)", quote_text, ticker, "Naver price")

    change, change_pct = _parse_naver_change(quote_text)
    previous_close = price - change if change is not None else None

    return Quote(
        ticker=ticker,
        price=price,
        previous_close=previous_close,
        change=change,
        change_pct=change_pct,
        currency="KRW",
        timestamp=timestamp,
        basis_label=basis_label,
    )


def _extract_naver_quote_text(page: str, code: str, ticker: str) -> str:
    blocks = re.findall(r"<dl\s+class=[\"']blind[\"']>(.*?)</dl>", page, flags=re.IGNORECASE | re.DOTALL)
    for block in blocks:
        text = _html_to_text(block)
        if code in text and "현재가" in text:
            return text

    raise MarketDataError(f"{ticker}: Naver Finance quote block not found")


def _html_to_text(raw_html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", raw_html)
    text = html_lib.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _parse_naver_timestamp(text: str) -> datetime | None:
    match = re.search(
        r"(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일\s*(\d{1,2})시\s*(\d{1,2})분",
        text,
    )
    if not match:
        return None

    year, month, day, hour, minute = (int(part) for part in match.groups())
    return datetime(year, month, day, hour, minute, tzinfo=KST)


def _parse_naver_basis_label(page: str) -> str | None:
    match = re.search(
        r'<em\s+class=["\']date["\']>\s*([0-9.]+)\s*<span>\s*기준\(([^<)]+)\)\s*</span>\s*</em>',
        page,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return None

    date = re.sub(r"\s+", " ", match.group(1)).strip()
    market_state = re.sub(r"\s+", " ", match.group(2)).strip()
    return f"{date} {market_state}".strip()


def _parse_required_number(pattern: str, text: str, ticker: str, field_name: str) -> float:
    match = re.search(pattern, text)
    if not match:
        raise MarketDataError(f"{ticker}: {field_name} not found")
    return _parse_number(match.group(1))


def _parse_naver_change(text: str) -> tuple[float | None, float | None]:
    if "전일대비" not in text:
        return None, None

    change_text = text.split("전일대비", 1)[1].split("전일가", 1)[0]
    sign = 0 if "보합" in change_text else 1
    if "하락" in change_text or "마이너스" in change_text:
        sign = -1
    elif "상승" in change_text or "플러스" in change_text:
        sign = 1

    numbers = re.findall(r"[0-9][0-9,]*(?:\.[0-9]+)?", change_text)
    change = sign * _parse_number(numbers[0]) if numbers else None
    change_pct = sign * _parse_number(numbers[1]) if len(numbers) > 1 else None
    return change, change_pct


def _fetch_tradingview_quote(ticker: str, code: str) -> Quote:
    body = json.dumps(
        {
            "symbols": {"tickers": [f"KRX:{code}"], "query": {"types": []}},
            "columns": ["name", "close", "change", "change_abs", "currency", "exchange"],
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        TRADINGVIEW_SCAN_URL,
        data=body,
        headers={
            "User-Agent": "Mozilla/5.0 telegram-scheduled-bot",
            "Content-Type": "application/json",
            "Origin": "https://www.tradingview.com",
            "Referer": "https://www.tradingview.com/",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")
        raise MarketDataError(f"{ticker}: TradingView HTTP {exc.code}: {body_text[:200]}") from exc
    except urllib.error.URLError as exc:
        raise MarketDataError(f"{ticker}: TradingView network error: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise MarketDataError(f"{ticker}: TradingView JSON decode error: {exc}") from exc

    rows = payload.get("data") or []
    if not rows:
        error = payload.get("error") or "empty response"
        raise MarketDataError(f"{ticker}: TradingView {error}")

    values = rows[0].get("d") or []
    price = _as_float(values[1] if len(values) > 1 else None)
    change_pct = _as_float(values[2] if len(values) > 2 else None)
    change = _as_float(values[3] if len(values) > 3 else None)
    currency = str(values[4] if len(values) > 4 and values[4] else "KRW")
    if price is None:
        raise MarketDataError(f"{ticker}: TradingView price missing")

    if change is not None and change_pct is not None:
        if change_pct < 0 < change:
            change = -change
        elif change_pct > 0 > change:
            change = abs(change)

    previous_close = price - change if change is not None else None
    return Quote(
        ticker=ticker,
        price=price,
        previous_close=previous_close,
        change=change,
        change_pct=change_pct,
        currency=currency,
        timestamp=datetime.now(tz=KST),
        basis_label=None,
    )


def _parse_number(value: str) -> float:
    return float(value.replace(",", ""))


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
