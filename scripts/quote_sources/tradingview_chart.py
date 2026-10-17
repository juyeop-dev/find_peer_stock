"""Read split-adjusted, regular-session bars from public TradingView charts.

The optional websocket-client dependency is needed only for live requests.
Use the anonymous chart connection; no account credentials are accepted here.
"""
from __future__ import annotations

import json
import math
import secrets
import threading
import time
from typing import Any


class ChartHistoryError(ValueError):
    """A chart response could not prove the requested series or identity."""


class ChartInstrumentError(ChartHistoryError):
    def __init__(self, symbol: str, info: dict):
        self.proof = {"symbol": symbol, **{key: info.get(key) for key in ("type", "description", "source_id", "pro_name")}}
        super().__init__(f"{symbol}: resolved instrument is {info.get('type')}, not an equity")


_clients = threading.local()
_paused = threading.Event()


def encode_message(method: str, params: list) -> str:
    body = json.dumps({"m": method, "p": params}, separators=(",", ":"), ensure_ascii=True)
    return f"~m~{len(body.encode('utf-8'))}~m~{body}"


def decode_messages(frame: str) -> list[str]:
    # TradingView frame lengths count JavaScript UTF-16 code units, not UTF-8
    # bytes. This matters for symbols whose descriptions include e.g. ® or é.
    data = frame.encode("utf-16-le")
    marker = "~m~".encode("utf-16-le")
    result = []
    while data:
        if not data.startswith(marker):
            raise ChartHistoryError("Invalid chart message framing")
        delimiter = data.find(marker, len(marker))
        if delimiter < 0:
            raise ChartHistoryError("Incomplete chart message length")
        try:
            length = int(data[len(marker):delimiter].decode("utf-16-le")) * 2
        except ValueError as exc:
            raise ChartHistoryError("Invalid chart message length") from exc
        data = data[delimiter + len(marker):]
        if length < 0 or length > len(data):
            raise ChartHistoryError("Truncated chart message")
        result.append(data[:length].decode("utf-16-le"))
        data = data[length:]
    return result


def parse_chart_bars(points: list[dict], *, require_volume: bool = True) -> list[dict[str, float]]:
    bars = {}
    for point in points:
        values = point.get("v") if isinstance(point, dict) else None
        if not isinstance(values, list) or len(values) < 6:
            raise ChartHistoryError("Invalid chart OHLCV array")
        if any(type(value) not in (float, int) or not math.isfinite(value) for value in values[:5]):
            raise ChartHistoryError("Missing or nonfinite chart OHLCV")
        stamp, opening, high, low, close, volume = values[:6]
        volume_available = type(volume) in (float, int) and math.isfinite(volume) and volume >= 0
        if not volume_available:
            if require_volume:
                raise ChartHistoryError("Missing or invalid chart volume")
            # Complete monthly price history determines all-time highs; its
            # volume is never used for turnover or daily eligibility. Some old
            # corporate-action bars contain missing/negative monthly volume.
            volume = 0
        # Some London foreign listings publish a zero low with otherwise valid
        # traded prices. Preserve that sentinel; new-high rules need high/open/
        # close and volume, so an unavailable low must not drop the whole series.
        if any(value <= 0 for value in (opening, high, close)) or low < 0:
            raise ChartHistoryError(f"Invalid chart prices or volume: {values[:6]}")
        if high < max(opening, low, close) or low > min(opening, high, close):
            raise ChartHistoryError("Inconsistent chart OHLC range")
        bar = dict(timestamp=stamp, open=opening, high=high, low=low, close=close, volume=volume)
        if not volume_available:
            bar["volume_unavailable"] = True
        if stamp in bars and bars[stamp] != bar:
            raise ChartHistoryError("Conflicting duplicate chart timestamp")
        bars[stamp] = bar
    return sorted(bars.values(), key=lambda bar: bar["timestamp"])


def fetch_chart(symbol: str, interval: str, count: int, *, timeout: float = 30) -> dict[str, Any]:
    if interval not in {"1D", "1M"} or not 1 <= count <= 5000:
        raise ChartHistoryError("Unsupported chart interval or count")
    try:
        import websocket
    except ImportError as exc:
        raise ChartHistoryError("Install scripts/requirements-chart-history.txt for live chart requests") from exc
    if _paused.is_set():
        raise ChartHistoryError("Chart rate limit: collection paused until a later run")
    session = "cs_" + secrets.token_hex(6)
    info, points = None, []
    ws = getattr(_clients, "connection", None)
    complete = False
    try:
        if ws is None or not ws.connected:
            ws = websocket.create_connection("wss://data.tradingview.com/socket.io/websocket",
                                             origin="https://www.tradingview.com", timeout=timeout)
            _clients.connection = ws
            ws.send(encode_message("set_auth_token", ["unauthorized_user_token"]))
        ws.settimeout(timeout)
        time.sleep(0.25)
        commands = [
            ("chart_create_session", [session, ""]),
            ("resolve_symbol", [session, "symbol_1", "=" + json.dumps({
                "symbol": symbol, "adjustment": "splits", "session": "regular"})]),
            ("create_series", [session, "s1", "s1", "symbol_1", interval, count]),
        ]
        for method, params in commands:
            ws.send(encode_message(method, params))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            frame = ws.recv()
            if not frame:
                raise ChartHistoryError(f"{symbol}: chart connection closed before series completion")
            for body in decode_messages(frame):
                if body.startswith("~h~"):
                    ws.send(f"~m~{len(body.encode('utf-8'))}~m~{body}")
                    continue
                message = json.loads(body)
                method, params = message.get("m"), message.get("p", [])
                if params and isinstance(params[0], str) and params[0].startswith("cs_") and params[0] != session:
                    continue
                if method in {"critical_error", "protocol_error", "symbol_error", "series_error"}:
                    raise ChartHistoryError(f"{symbol}: {method}: {params}")
                if method == "symbol_resolved" and params[:2] == [session, "symbol_1"]:
                    info = params[2]
                    identity = info.get("pro_name") or info.get("full_name")
                    if identity != symbol:
                        raise ChartHistoryError(f"{symbol}: resolved to unexpected symbol {identity}")
                    if info.get("type") in {"index", "forex", "crypto", "futures", "bond", "economic"}:
                        raise ChartInstrumentError(symbol, info)
                elif method == "timescale_update" and params and params[0] == session:
                    points.extend(params[1].get("s1", {}).get("s", []))
                elif method == "series_completed" and params[:2] == [session, "s1"]:
                    if info is None:
                        raise ChartHistoryError(f"{symbol}: series completed without symbol identity")
                    result = {"symbol": symbol, "interval": interval, "requested_bars": count,
                            "info": {key: info.get(key) for key in (
                                "name", "pro_name", "full_name", "description", "exchange",
                                "source_id", "currency_code", "timezone", "first_bar_time", "type")},
                            "bars": parse_chart_bars(points, require_volume=interval == "1D")}
                    complete = True
                    return result
        raise ChartHistoryError(f"{symbol}: chart series timed out")
    except ChartHistoryError:
        raise
    except Exception as exc:
        if getattr(exc, "status_code", None) == 429:
            _paused.set()
            raise ChartHistoryError("Chart rate limit (429): collection paused; retry after cooldown") from exc
        raise ChartHistoryError(f"{symbol}: chart request failed: {type(exc).__name__}: {exc}") from exc
    finally:
        if ws is not None:
            if complete:
                try:
                    ws.send(encode_message("chart_delete_session", [session]))
                except Exception:
                    ws.close()
                    _clients.connection = None
            else:
                ws.close()
                _clients.connection = None
