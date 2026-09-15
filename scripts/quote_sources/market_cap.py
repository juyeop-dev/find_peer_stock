from __future__ import annotations

import json
import math
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Iterable


TRADINGVIEW_SCANNER_URL = "https://scanner.tradingview.com/{scanner}/scan"
MARKET_CAP_COLUMNS = ("name", "market_cap_basic", "fundamental_currency_code")
FX_COLUMNS = ("name", "close", "currency")


class MarketCapError(RuntimeError):
    pass


@dataclass(frozen=True)
class MarketCap:
    ticker: str
    value: float
    currency: str
    value_usd: float | None
    source: str = "TradingView"


def fetch_market_caps(tickers: Iterable[str], *, timeout: float = 30) -> dict[str, MarketCap]:
    requests_by_scanner: dict[str, dict[str, str]] = {}
    for ticker in tickers:
        for scanner, symbol in _symbol_candidates(ticker):
            requests_by_scanner.setdefault(scanner, {})[symbol] = ticker

    local_caps: dict[str, tuple[float, str]] = {}
    for scanner, symbol_map in requests_by_scanner.items():
        try:
            payload = _scan(scanner, symbol_map, MARKET_CAP_COLUMNS, timeout)
            local_caps.update(_parse_market_caps(payload, symbol_map))
        except MarketCapError:
            # One regional scanner should not hide successfully fetched regions.
            continue

    fx_rates = _fetch_usd_fx_rates({currency for _, currency in local_caps.values()}, timeout)
    result = {}
    for ticker, (value, currency) in local_caps.items():
        rate = fx_rates.get(currency)
        value_usd = value / rate if rate else None
        result[ticker] = MarketCap(ticker=ticker, value=value, currency=currency, value_usd=value_usd)
    return result


def _symbol_candidates(ticker: str) -> list[tuple[str, str]]:
    upper = ticker.upper()
    mappings = (
        (".KS", "korea", "KRX"),
        (".KQ", "korea", "KRX"),
        (".TWO", "taiwan", "TPEX"),
        (".TW", "taiwan", "TWSE"),
        (".T", "japan", "TSE"),
        (".HK", "hongkong", "HKEX"),
        (".SS", "china", "SSE"),
        (".SZ", "china", "SZSE"),
    )
    for suffix, scanner, exchange in mappings:
        if upper.endswith(suffix):
            code = upper[: -len(suffix)]
            if suffix == ".HK":
                code = code.lstrip("0") or "0"
            return [(scanner, f"{exchange}:{code}")]

    return [("america", f"{exchange}:{upper}") for exchange in ("NASDAQ", "NYSE", "AMEX")]


def _scan(scanner: str, symbol_map: dict[str, str], columns: tuple[str, ...], timeout: float) -> dict[str, Any]:
    payload = {
        "symbols": {"tickers": list(symbol_map), "query": {"types": []}},
        "columns": list(columns),
    }
    return _request_json(TRADINGVIEW_SCANNER_URL.format(scanner=scanner), payload, timeout)


def _request_json(url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, allow_nan=False).encode("utf-8"),
        headers={
            "User-Agent": "Mozilla/5.0 stock-peer-site",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.load(response)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise MarketCapError(f"Cannot read {url}: {exc}") from exc
    if not isinstance(result, dict) or not isinstance(result.get("data"), list):
        raise MarketCapError(f"Malformed scanner response from {url}")
    return result


def _parse_market_caps(payload: dict[str, Any], symbol_map: dict[str, str]) -> dict[str, tuple[float, str]]:
    result = {}
    for row in payload["data"]:
        if not isinstance(row, dict) or row.get("s") not in symbol_map:
            continue
        values = row.get("d")
        if not isinstance(values, list) or len(values) != len(MARKET_CAP_COLUMNS):
            continue
        value = _positive_number(values[1])
        currency = _currency(values[2])
        if value is None or currency is None:
            continue
        ticker = symbol_map[row["s"]]
        result.setdefault(ticker, (value, currency))
    return result


def _fetch_usd_fx_rates(currencies: set[str], timeout: float) -> dict[str, float]:
    rates = {"USD": 1.0}
    requested = sorted(currency for currency in currencies if currency != "USD")
    if not requested:
        return rates

    symbol_map = {f"FX_IDC:USD{currency}": currency for currency in requested}
    try:
        payload = _scan("forex", symbol_map, FX_COLUMNS, timeout)
    except MarketCapError:
        return rates

    for row in payload["data"]:
        if not isinstance(row, dict) or row.get("s") not in symbol_map:
            continue
        values = row.get("d")
        if not isinstance(values, list) or len(values) != len(FX_COLUMNS):
            continue
        rate = _positive_number(values[1])
        if rate is not None:
            rates[symbol_map[row["s"]]] = rate
    return rates


def _positive_number(value: Any) -> float | None:
    if type(value) not in {int, float} or not math.isfinite(value) or value <= 0:
        return None
    return float(value)


def _currency(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    currency = value.strip().upper()
    return currency if len(currency) == 3 and currency.isalpha() else None
