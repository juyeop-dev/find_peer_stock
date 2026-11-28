"""Prepend verified 2013 observations from the report collectors' originals."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
import gzip
import hashlib
import json
import math
from urllib.parse import quote

from backfill_korean_new_highs import history_url, parse_history
from backfill_rebounds import verified_source
from backfill_yahoo_calendars import BackfillError, request_yahoo
from extend_stock_history_2023 import cached_yahoo_path
import stock_chart_history as charts

ROOT = charts.ROOT
AUDIT = ROOT / "data/information-audit/2013"
VERIFIED_2014 = ROOT / "data/tmp_2014/deploy-worktree/frontend/public/data/stock-history"
START, END = "2012-12-20", "2013-12-31"
MARKETS_BY_SUFFIX = {"KS": "korea", "KQ": "korea", "T": "japan", "TW": "taiwan",
                     "TWO": "taiwan", "SS": "china", "SZ": "china"}


def originals(ticker, market):
    symbol = charts.yahoo_symbol(ticker)
    if symbol:
        for year in (2013, 2014):
            yield cached_yahoo_path(symbol, year), charts.parse_yahoo, ticker
    if market == "korea":
        yield ROOT / "data/tmp_2013/semiconductor" / f"{ticker}.json", charts.parse_yahoo, ticker
        code = ticker.split(".")[0]
        for first, last in [(date(2012, 1, 4), date(2013, 12, 30)),
                            (date(2012, 12, 18), date(2014, 12, 30))]:
            url = history_url(code, first, last)
            path = ROOT / "data/tmp_korean_history" / (hashlib.sha256(url.encode()).hexdigest() + ".json")

            def parse_naver(payload, name, first=first, last=last, code=code):
                rows = parse_history(payload, code=code, start=first, end=last)
                return {"ticker": name, "currency": "KRW", "source": "Naver Finance adjusted daily history",
                        "prices": [[str(day), row[4], row[4]] for day, row in sorted(rows.items())]}

            yield path, parse_naver, ticker
    tv_symbol = ticker if ":" in ticker else None
    if market == "taiwan":
        exchange = "TPEX" if ticker.endswith(".TWO") else "TWSE"
        tv_symbol = f"{exchange}:{ticker.split('.')[0]}"
    if tv_symbol:
        for count in (3700, 3200):
            digest = hashlib.sha256(f"{tv_symbol}:1D:{count}".encode()).hexdigest()
            yield ROOT / "data/tmp_tradingview_chart/1D" / f"{digest}.json", charts.parse_tradingview, tv_symbol


def extend(previous, market, sessions, saturday_quotes):
    ticker = previous["ticker"]
    existing = {point[0]: point for point in previous["prices"]}
    points = dict(existing)
    split_only = all(point[1] == point[2] for point in previous["prices"])
    evidence = dict(previous.get("historical_2013_extension", {}).get("sources", {}))
    for path, parse, name in originals(ticker, market):
        if not path.exists():
            continue
        try:
            raw = path.read_bytes()
            original = parse(json.loads(raw), name)
        except (KeyError, ValueError, TypeError, IndexError):
            continue
        if original["currency"] != previous["currency"]:
            continue
        checksum = hashlib.sha256(raw).hexdigest()
        verified = {point[0]: point for point in original["prices"]
                    if not point[0].startswith("2013-") or point[0] in sessions}
        for day, item in saturday_quotes.get(name, {}).items():
            if item["chart_sha256"] == checksum:
                close = item["original_bar"]["close"] * item["factor"]
                verified[day] = [day, close, close]
        candidates = {day: [day, close, close if split_only else adjusted]
                      for day, (_, close, adjusted) in verified.items()}
        overlap = [(existing[day], point) for day, point in candidates.items() if day in existing]
        if len(overlap) < 3 or not all(math.isclose(a, b, rel_tol=1e-5, abs_tol=.005)
                                      for before, after in overlap for a, b in zip(before[1:], after[1:])):
            continue
        added = {day: point for day, point in candidates.items() if START <= day <= END and day not in points}
        if added:
            points.update(added)
            evidence[path.relative_to(ROOT).as_posix()] = {"sha256": checksum, "provider": original["source"],
                                                           "added": len(added), "verified_overlap": len(overlap)}
    if len(points) == len(existing):
        return previous
    return {**previous, "prices": [points[day] for day in sorted(points)],
            "historical_2013_extension": {"sources": evidence}}


def restore_verified_baseline(previous, value, market, sessions, saturday_quotes, filename):
    if previous["prices"][0][0] <= END or value["prices"][0][0] <= END:
        return value
    path = VERIFIED_2014 / f"{filename}.json.gz"
    if not path.exists():
        return value
    raw = path.read_bytes()
    baseline = json.loads(gzip.decompress(raw))
    if baseline.get("ticker") != previous["ticker"] or baseline.get("currency") != previous["currency"]:
        return value
    restored = extend(baseline, market, sessions, saturday_quotes)
    if restored is baseline:
        return value
    existing = {point[0]: point for point in previous["prices"]}
    split_only = all(point[1] == point[2] for point in previous["prices"])
    older = {day: [day, close, close if split_only else adjusted] for day, close, adjusted in restored["prices"]}
    overlap = [(point, older[day]) for day, point in existing.items() if day in older]
    if len(overlap) < 3 or not all(math.isclose(a, b, rel_tol=1e-5, abs_tol=.005)
                                  for before, after in overlap for a, b in zip(before[1:], after[1:])):
        return value
    merged = {**{day: point for day, point in older.items() if day < previous["prices"][0][0]}, **existing}
    evidence = {**restored["historical_2013_extension"], "baseline_2014_sha256": hashlib.sha256(raw).hexdigest(),
                "baseline_2014_overlap": len(overlap)}
    return {**previous, "prices": [merged[day] for day in sorted(merged)], "historical_2013_extension": evidence}


def main():

    calendar = json.loads((ROOT / "data/market-closures/2013.json").read_bytes())
    weekdays = {str(day) for offset in range(365)
                if (day := date(2013, 1, 1) + timedelta(days=offset)).weekday() < 5}
    sessions = {row["market"]: (weekdays | row.get("additional_open_dates", {}).keys()) - row["dates"].keys()
                for row in calendar["markets"]}
    saturday_quotes = {}
    for path in sorted(AUDIT.glob("taiwan-official-recovery-*.json")):
        proof = json.loads(path.read_bytes())
        for symbol, value in proof["members"].items():
            saturday_quotes.setdefault(symbol, {})[proof["date"]] = value
    counts, updated, covered = Counter(), Counter(), Counter()
    history_dir = ROOT / "frontend/public/data/stock-history"
    for path in sorted(charts.PACKS.glob("[0-9a-f].json.gz")):
        stock_histories = json.loads(gzip.decompress(path.read_bytes()))
        changed = False
        for ticker, previous in stock_histories.items():
            _, separator, suffix = ticker.rpartition(".")
            market = MARKETS_BY_SUFFIX.get(suffix) if separator else None
            if ticker.startswith(("EURONEXT:", "XETR:", "SIX:", "LSE:")):
                market = "europe"
            if market is None and previous["currency"] == "USD":
                market = "us"
            if market is None:
                continue
            if not previous.get("prices") or (previous.get("first_trade_date") or "") > END:
                continue
            filename = quote(ticker, safe="").replace("%", "~")
            value = extend(previous, market, sessions[market], saturday_quotes)
            value = restore_verified_baseline(previous, value, market, sessions[market], saturday_quotes, filename)
            n = sum(START < day <= END and day.startswith("2013-") and day in sessions[market] for day, *_ in value["prices"])
            if n:
                counts[market] += 1
            if value.get("historical_2013_extension"):
                covered[market] += 1
            if value is not previous:
                updated[market] += 1
                stock_histories[ticker] = value
                target = history_dir / f"{filename}.json.gz"
                retained = json.loads(gzip.decompress(target.read_bytes())) if target.exists() else {}
                published = {**value, "prior_snapshots": [curve for curve in value.get("prior_snapshots", [])
                             if curve.get("complete_history") and curve["currency"] == value["currency"] == "KRW"]}
                if "sector_quotes" in retained:
                    published["sector_quotes"] = retained["sector_quotes"]
                temporary = target.with_suffix(".gz.tmp")
                temporary.write_bytes(gzip.compress(json.dumps(published, ensure_ascii=False, separators=(",", ":"),
                                                              allow_nan=False).encode(), mtime=0))
                temporary.replace(target)
                changed = True
        if changed:
            temporary = path.with_suffix(".gz.tmp")
            temporary.write_bytes(gzip.compress(json.dumps(stock_histories, ensure_ascii=False, separators=(",", ":"),
                                                          allow_nan=False).encode(), compresslevel=6, mtime=0))
            temporary.replace(path)
        print(f"2013 price shard {path.stem}: {dict(updated)}", flush=True)
    charts.write_json(AUDIT / "price-collection.json", {"updated": dict(updated), "extended": dict(covered),
                                                        "tickers_with_2013_sessions": dict(counts)})


def collect_korean_originals():
    import pyarrow.parquet as pq

    original = ROOT / "data/tmp_korea_recalculation/source/marcap-2013.parquet"
    verified_source(original)
    listings = set()
    for batch in pq.ParquetFile(original).iter_batches(columns=["Code", "Market"]):
        for row in batch.to_pylist():
            code, board = row["Code"], row["Market"]
            if board == "KOSPI" or board.startswith("KOSDAQ"):
                listings.add(code + (".KS" if board == "KOSPI" else ".KQ"))
    start, end = date(2013, 1, 1) - timedelta(days=370), date(2013, 12, 31) + timedelta(days=2)
    cache = ROOT / "data/tmp_calendar_history"

    def collect(ticker):
        try:
            payload = request_yahoo(ticker, period1=start, period2=end, range_name=None, interval="1d",
                                    timeout=15, cache_dir=cache, retries=2)
            parsed = charts.parse_yahoo(payload, ticker)
            return ticker, sum(day.startswith("2013-") for day, *_ in parsed["prices"]), None
        except (BackfillError, KeyError, ValueError, TypeError, IndexError) as error:
            return ticker, 0, str(error)

    results = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        for ticker, observations, error in pool.map(collect, sorted(listings)):
            results.append({"ticker": ticker, "observations": observations, "error": error})
            if len(results) % 200 == 0:
                print(f"2013 Korean chart originals: {len(results)}/{len(listings)}", flush=True)
    charts.write_json(AUDIT / "korean-price-source.json", {"results": results})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collect-korea", action="store_true", help="Cache original dated Yahoo charts for actual Korean listings")
    if parser.parse_args().collect_korea:
        collect_korean_originals()
    else:
        main()
