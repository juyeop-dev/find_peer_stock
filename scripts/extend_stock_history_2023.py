"""Extend published prices from cached originals only after verifying the overlap.

Keeps every existing point, currency and recent quote. Spark and TradingView
store split-adjusted closes in both price columns; preserve that convention.
Dividend-adjusted archives must match both columns before they can be joined.
"""
import argparse
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
from urllib.parse import quote, urlencode

import stock_chart_history as charts
import stock_information as info
from backfill_yahoo_calendars import _cache_path


def join_prices(previous, older):
    if previous["ticker"] != older["ticker"] or previous["currency"] != older["currency"]:
        raise ValueError("Listing or currency differs")
    if not previous["prices"] or not older["prices"]:
        return None
    existing = {point[0]: point for point in previous["prices"]}
    split_only = all(point[1] == point[2] for point in previous["prices"])
    candidates = [[day, close, close if split_only else adjusted] for day, close, adjusted in older["prices"]]
    overlap = [(point, existing[point[0]]) for point in candidates if point[0] in existing]
    if len(overlap) < 3 or not all(math.isclose(a, b, rel_tol=1e-5, abs_tol=.005)
                                  for left, right in overlap for a, b in zip(left[1:], right[1:])):
        return None
    prefix = [point for point in candidates if "2022-12-20" <= point[0] < previous["prices"][0][0]]
    if not prefix:
        return None
    return {**previous, "prices": prefix + previous["prices"],
            "first_trade_date": previous.get("first_trade_date") or older.get("first_trade_date")}


def cached_yahoo_path(symbol):
    start = date(2023, 1, 1) - timedelta(days=370)
    end = date(2023, 12, 31) + timedelta(days=2)
    params = {"interval": "1d", "events": "splits", "includePrePost": "false",
              "period1": str(int(datetime.combine(start, time(), timezone.utc).timestamp())),
              "period2": str(int(datetime.combine(end, time(), timezone.utc).timestamp()))}
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol, safe='')}?{urlencode(params)}"
    return _cache_path(info.ROOT / "data/tmp_calendar_history", "1d-dated", url)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, default=info.ROOT / "data/tmp_2023_history")
    args = parser.parse_args()
    charts.DATABASE = args.state_dir / "history.sqlite"
    db = charts.database()
    progress = info.open_database(args.state_dir)
    progress.execute("CREATE TABLE IF NOT EXISTS history_2023_updates(ticker TEXT PRIMARY KEY,value TEXT NOT NULL)")
    results = []
    for row in charts.roster():
        stored = db.execute("SELECT value FROM history WHERE ticker=?", (row["ticker"],)).fetchone()
        if not stored:
            continue
        previous = json.loads(stored[0])
        prices = previous["prices"]
        if len(prices) < 2:
            continue
        result = {"ticker": row["ticker"], "order": row["order"], "updated": True, "error": None,
                  "queried_at": datetime.now(timezone.utc).isoformat()}
        if prices[0][0] <= "2023-01-01" or previous.get("first_trade_date", "") and previous["first_trade_date"] > "2023-01-01":
            result["cache_status"] = "already_covered" if prices[0][0] <= "2023-01-01" else "later_listing"
        else:
            candidates = []
            if symbol := charts.yahoo_symbol(row["ticker"]):
                candidates.append((cached_yahoo_path(symbol), "yahoo"))
            if ":" in row["ticker"]:
                digest = hashlib.sha256(f"{row['ticker']}:1D:1500".encode()).hexdigest()
                candidates.append((info.ROOT / "data/tmp_tradingview_chart/1D" / f"{digest}.json", "tradingview"))
            value = None
            for path, provider in candidates:
                if not path.exists():
                    continue
                try:
                    raw = path.read_bytes()
                    payload = json.loads(raw)
                    older = (charts.parse_yahoo if provider == "yahoo" else charts.parse_tradingview)(payload, row["ticker"])
                    value = join_prices(previous, older)
                    if value:
                        result.update(cache_status="overlap_verified", cache=str(path.relative_to(info.ROOT)), sha256=hashlib.sha256(raw).hexdigest())
                        value["historical_2023_extension"] = {"source": older["source"], "cache": result["cache"], "sha256": result["sha256"],
                            "verified_at": result["queried_at"], "price_convention": "split-adjusted close" if all(p[1] == p[2] for p in previous["prices"]) else "original close and adjusted close"}
                        db.execute("UPDATE history SET value=? WHERE ticker=?", (json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False), row["ticker"]))
                        db.commit()
                        break
                except (KeyError, ValueError, TypeError, IndexError):
                    continue
            if not value:
                continue
        progress.execute("INSERT OR REPLACE INTO history_2023_updates VALUES (?,?)", (row["ticker"], json.dumps(result)))
        progress.commit()
        results.append(result)
    charts.write_json(info.AUDIT / "2023/history-cache-import.json", {"counts": dict(Counter(r["cache_status"] for r in results)), "results": results})
    print(dict(Counter(r["cache_status"] for r in results)), flush=True)
    db.close()
    progress.close()


if __name__ == "__main__":
    main()
