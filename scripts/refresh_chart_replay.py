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
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "data/chart-replay/markets.json"
PUBLIC = ROOT / "frontend/public/data/chart-replay/markets.json"
SYMBOLS = [("^KS11", "코스피", "Asia/Seoul"), ("GC=F", "금 선물 (연속)", "America/New_York")]


def collect_kospi() -> dict:
    # Yahoo omits some observed KOSPI sessions (including 2022-01-03).
    # Use one continuous Naver index history rather than splicing providers.
    url = "https://fchart.stock.naver.com/sise.nhn?symbol=KOSPI&timeframe=day&count=3000&requestType=0"
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
        if day < "2017-01-01" or day >= today:
            continue
        opening, high, low, close, volume = map(float, (opening, high, low, close, volume))
        if not all(math.isfinite(v) and v > 0 for v in (opening, high, low, close)) or low > min(opening, close) or high < max(opening, close) or not math.isfinite(volume) or volume < 0:
            raise ValueError("Invalid Naver index OHLC/volume")
        bars.append({"date": day, "open": opening, "high": high, "low": low, "close": close, "adjusted_close": close, "volume": volume})
    if len(bars) < 250 or len({b["date"] for b in bars}) != len(bars):
        raise ValueError("Insufficient or duplicate Naver index sessions")
    return {"ticker": "^KS11", "name": "코스피", "currency": "KRW", "source": "Naver Finance · KOSPI (^KS11)", "source_url": url, "bars": bars}


def collect(ticker: str, name: str, zone: str) -> dict:
    query = urllib.parse.urlencode({"period1": 1483228800, "period2": int(datetime.now(timezone.utc).timestamp()), "interval": "1d"})
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
        if day >= datetime.now(ZoneInfo(zone)).strftime("%Y-%m-%d"):
            continue
        adj = adjusted[i] if i < len(adjusted) else close
        volume = quote.get("volume", [None] * len(result["timestamp"]))[i]
        bars.append({"date": day, "open": opening, "high": high, "low": low, "close": close,
                     "adjusted_close": adj if isinstance(adj, (int, float)) and math.isfinite(adj) and adj > 0 else close,
                     "volume": volume if isinstance(volume, (int, float)) and math.isfinite(volume) and volume >= 0 else None})
    if len(bars) < 250 or len({b["date"] for b in bars}) != len(bars):
        raise ValueError("Insufficient or duplicate provider sessions")
    return {"ticker": ticker, "name": name, "currency": result["meta"]["currency"],
            "source": "Yahoo Finance · " + ticker, "source_url": url, "bars": bars}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args()
    if not args.publish:
        markets = [collect_kospi(), collect(*SYMBOLS[1])]
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
