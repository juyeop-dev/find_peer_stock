"""Collect real index/futures OHLC for the local replay workspace.

Run directly to refresh; --publish copies the retained snapshot without network.
Gold is Yahoo's GC=F continuous futures series, not spot gold or a fixed contract.
"""
from __future__ import annotations

import argparse
import json
import math
import shutil
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from price_history_range import load_price_range
from historical_sessions import verified_sessions
from history_policy import DEFAULT_POLICY

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "data/chart-replay/markets.json"
PUBLIC = ROOT / "frontend/public/data/chart-replay/markets.json"
SYMBOLS = [("^KS11", "코스피", "Asia/Seoul"), ("GC=F", "금 선물 (연속)", "America/New_York")]


def collect_kospi(history_request=None) -> dict:
    history_request = history_request or load_price_range()
    first_year_end = min(history_request.end, history_request.start[:4] + "-12-31")
    expected = verified_sessions(history_request.start, first_year_end, "korea", root=ROOT)
    if not expected:
        raise ValueError("No verified replay start session")
    expected_start = expected[0].isoformat()
    # Yahoo omits some observed KOSPI sessions (including 2022-01-03).
    # Use one continuous Naver index history rather than splicing providers.
    url = "https://fchart.stock.naver.com/sise.nhn?symbol=KOSPI&timeframe=day&count=3500&requestType=0"
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 StockPeer"})
    with urllib.request.urlopen(request, timeout=45) as response:
        root = ET.fromstring(response.read().decode("euc-kr"))
    chart = root.find("chartdata")
    if chart is None or chart.get("symbol") != "KOSPI":
        raise ValueError("Naver index identity mismatch")
    bars = []
    today = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")
    for item in chart.iter("item"):
        day, opening, high, low, close, volume = item.attrib["data"].split("|")
        day = datetime.strptime(day, "%Y%m%d").strftime("%Y-%m-%d")
        if day < history_request.start or day > history_request.end or day >= today:
            continue
        opening, high, low, close, volume = map(float, (opening, high, low, close, volume))
        if not all(math.isfinite(v) and v > 0 for v in (opening, high, low, close)) or low > min(opening, close) or high < max(opening, close) or not math.isfinite(volume) or volume < 0:
            raise ValueError("Invalid Naver index OHLC/volume")
        bars.append({"date": day, "open": opening, "high": high, "low": low, "close": close, "adjusted_close": close, "volume": volume})
    if len(bars) < min(250, max(2, (date.fromisoformat(history_request.end) - date.fromisoformat(history_request.start)).days // 2)) or len({b["date"] for b in bars}) != len(bars):
        raise ValueError("Insufficient or duplicate Naver index sessions")
    # Naver's XML endpoint silently caps index rows at about 3,000 even when
    # count is larger. Extend only with verified same-provider index pages.
    if bars[0]["date"] > expected_start:
        archived = json.loads((ROOT / "data/investors/index.json").read_bytes())
        indices = {row['date']: market['index'] for row in archived['history']
                   for market in row['markets'] if market['market'] == 'KOSPI'}
        overlap = [bar for bar in bars if bar['date'] in indices]
        if len(overlap) < 3 or any(not math.isclose(bar[key], indices[bar['date']][key], rel_tol=1e-10, abs_tol=.005)
                                  for bar in overlap for key in ['open', 'high', 'low', 'close']):
            raise ValueError('Naver index page and XML OHLC bases differ')
        prefix = []
        for day, row in sorted(indices.items()):
            if not history_request.start <= day < bars[0]['date']:
                continue
            if row['date'] != day or not all(type(row.get(key)) in [int, float] and math.isfinite(row[key]) and row[key] > 0 for key in ['open', 'high', 'low', 'close']):
                raise ValueError('Historical Naver index OHLC is incomplete')
            if row['low'] > min(row['open'], row['close']) or row['high'] < max(row['open'], row['close']):
                raise ValueError('Historical Naver index OHLC bounds differ')
            prefix.append({key: row[key] for key in ['date', 'open', 'high', 'low', 'close']} |
                          {'adjusted_close': row['close'], 'volume': None})
        if not prefix or prefix[0]['date'] != expected_start:
            raise ValueError('The capped XML response requires the verified requested index prefix')
        bars = prefix + bars
    return {"ticker": "^KS11", "name": "코스피", "currency": "KRW", "source": "Naver Finance · KOSPI (^KS11)", "source_url": url,
            "historical_index_source": "https://m.stock.naver.com/api/index/KOSPI/price?pageSize=60",
            "historical_volume_note": "The older validated index page supplies OHLC; unavailable volume remains null.", "bars": bars}


def collect(ticker: str, name: str, zone: str, history_request=None) -> dict:
    history_request = history_request or load_price_range()
    query = urllib.parse.urlencode({"period1": int(datetime.fromisoformat(history_request.start).replace(tzinfo=timezone.utc).timestamp()), "period2": min(int(datetime.now(timezone.utc).timestamp()), int(datetime.fromisoformat(history_request.end).replace(tzinfo=timezone.utc).timestamp()) + 86400), "interval": "1d"})
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(ticker, safe='')}?{query}"
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 StockPeer", "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=45) as response:
        payload = json.load(response)
    if payload["chart"].get("error"):
        raise ValueError(payload["chart"]["error"])
    result = payload["chart"]["result"][0]
    if result["meta"]["symbol"].upper() != ticker.upper():
        raise ValueError("Provider symbol mismatch")
    quote = result["indicators"]["quote"][0]
    adjusted = result["indicators"].get("adjclose", [{}])[0].get("adjclose", [])
    bars = []
    for i, timestamp in enumerate(result["timestamp"]):
        values = [quote[key][i] for key in ("open", "high", "low", "close")]
        if any(not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0 for v in values):
            continue
        opening, high, low, close = values
        if low > min(opening, close) or high < max(opening, close):
            raise ValueError("Invalid provider OHLC")
        day = datetime.fromtimestamp(timestamp, ZoneInfo(zone)).strftime("%Y-%m-%d")
        # Current sessions may be incomplete. Only persist completed past dates.
        if day < history_request.start or day > history_request.end or day >= datetime.now(ZoneInfo(zone)).strftime("%Y-%m-%d"):
            continue
        adj = adjusted[i] if i < len(adjusted) else close
        volume = quote.get("volume", [None] * len(result["timestamp"]))[i]
        bars.append({"date": day, "open": opening, "high": high, "low": low, "close": close,
                     "adjusted_close": adj if isinstance(adj, (int, float)) and math.isfinite(adj) and adj > 0 else close,
                     "volume": volume if isinstance(volume, (int, float)) and math.isfinite(volume) and volume >= 0 else None})
    if len(bars) < min(250, max(2, (date.fromisoformat(history_request.end) - date.fromisoformat(history_request.start)).days // 2)) or len({b["date"] for b in bars}) != len(bars):
        raise ValueError("Insufficient or duplicate provider sessions")
    return {"ticker": ticker, "name": name, "currency": result["meta"]["currency"],
            "source": "Yahoo Finance · " + ticker, "source_url": url, "bars": bars}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--history-config", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        history_request = load_price_range(args.history_config)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    if args.dry_run:
        print(json.dumps({"start": history_request.start, "end": history_request.end})); return
    if not args.publish:
        markets = [collect_kospi(history_request), collect(*SYMBOLS[1], history_request)]
        snapshot = {"schema_version": 1, "fetched_at": datetime.now(timezone.utc).isoformat(), "markets": markets}
        SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
        temporary = SNAPSHOT.with_suffix(".tmp")
        temporary.write_text(json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"), allow_nan=False), encoding="utf-8")
        temporary.replace(SNAPSHOT)
    PUBLIC.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SNAPSHOT, PUBLIC)
    snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    print(json.dumps({"markets": [{"ticker": row["ticker"], "bars": len(row["bars"]), "from": row["bars"][0]["date"], "to": row["bars"][-1]["date"]} for row in snapshot["markets"]]}))


if __name__ == "__main__":
    main()
