"""Prepend verified 2013 OHLC to both saved replay curves."""
import hashlib
import json
import math

import refresh_chart_replay as replay
from stock_chart_history import write_json

GOLD_URL = ("https://query1.finance.yahoo.com/v8/finance/chart/GC%3DF"
            "?period1=1356998400&period2=1391212800&interval=1d&events=splits&includePrePost=false")
OHLC = ("open", "high", "low", "close", "adjusted_close")


def prepend(old, observations):
    original = {row["date"]: row for row in observations}
    common = [row for row in old if row["date"] in original]
    if len(common) < 3 or any(not math.isclose(row[key], original[row["date"]][key], rel_tol=1e-5, abs_tol=.005)
                              for row in common for key in OHLC):
        raise ValueError("Archived and original replay OHLC differ on common trading days")
    prefix = [original[day] for day in sorted(original) if "2013-01-01" <= day < min("2014-01-01", old[0]["date"])]
    return prefix + old, len(prefix)


def main():
    root = replay.ROOT
    investor_file = root / "data/investors/index.json"
    gold_file = root / "data/tmp_2013/sources/gold.json"
    investor_raw, gold_raw = investor_file.read_bytes(), gold_file.read_bytes()
    archive = json.loads(investor_raw)
    indices = [market["index"] for row in archive["history"] for market in row["markets"] if market["market"] == "KOSPI"]
    kospi = [{**{key: row[key] for key in ("date", "open", "high", "low", "close")},
              "adjusted_close": row["close"], "volume": None} for row in indices if row["date"][:4] in {"2013", "2014"}]
    if sum(row["date"].startswith("2013-") for row in kospi) != 247:
        raise ValueError("Incomplete 2013 KOSPI sessions")
    gold = replay.parse_yahoo_replay(json.loads(gold_raw), *replay.SYMBOLS[1], GOLD_URL)
    current = json.loads(replay.SNAPSHOT.read_bytes())
    series = {"^KS11": (kospi, investor_raw), "GC=F": (gold["bars"], gold_raw)}
    counts = {}
    for market in current["markets"]:
        observations, raw = series[market["ticker"]]
        if market["ticker"] == "GC=F" and market["currency"] != gold["currency"]:
            raise ValueError("Gold replay currency differs from the original")
        market["bars"], added = prepend(market["bars"], observations)
        count = sum(row["date"].startswith("2013-") for row in market["bars"])
        if count < 240:
            raise ValueError(f"Incomplete 2013 replay series {market['ticker']}: {count}")
        counts[market["ticker"]] = {"observations": count, "added": added, "source_sha256": hashlib.sha256(raw).hexdigest()}
    write_json(replay.SNAPSHOT, current)
    write_json(replay.PUBLIC, current)
    write_json(root / "data/information-audit/2013/replay.json", counts)
    print({ticker: result["observations"] for ticker, result in counts.items()}, flush=True)


if __name__ == "__main__":
    main()
