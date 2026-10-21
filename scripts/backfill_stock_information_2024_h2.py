"""Resume reported H2-2024 statements in roster order without replacing newer data.

Uses an isolated SQLite database seeded from the current checked-in information
packs, rather than a possibly older database left by an earlier collection run.
Every result is committed individually; rerunning skips completed lookups.
"""
from __future__ import annotations

import argparse
import hashlib
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from urllib.parse import quote, urlencode
from functools import cache

import stock_chart_history as charts
import stock_information as info

STATE = info.ROOT / "data/tmp_2024_h2"
AUDIT = info.ROOT / "data/information-audit/2024-h2"
START = "2024-07-01"
END = "2024-12-31"


@cache
def european_listings():
    path = info.ROOT / "data/tmp_tradingview_chart/universe.json"
    return {row["symbol"]: row for row in json.loads(path.read_text(encoding="utf-8"))["rows"]} if path.exists() else {}


def resolve_yahoo(row):
    if symbol := charts.yahoo_symbol(row["ticker"]):
        return symbol
    if not row["ticker"].startswith("EURONEXT:"):
        return None
    listing = european_listings().get(row["ticker"])
    if not listing:
        return None
    path = STATE / "mappings" / (hashlib.sha256(row["ticker"].encode()).hexdigest() + ".json")
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))["symbol"]
    from backfill_yahoo_calendars import _company_name_matches
    venues = {"PA": "PAR", "AS": "AMS", "BR": "BRU", "LS": "LIS", "IR": "ISE"}
    matches = []
    for suffix, exchange in venues.items():
        symbol = row["ticker"].split(":", 1)[1] + "." + suffix
        try:
            payload = info.fetch_json(f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol, safe='')}?range=5d&interval=1d")
            meta = payload["chart"]["result"][0]["meta"]
            if meta.get("symbol") == symbol and meta.get("exchangeName") == exchange and meta.get("instrumentType") == "EQUITY" and meta.get("currency", "").upper() == listing["currency"].upper() and _company_name_matches(listing["description"], meta):
                matches.append({"symbol": symbol, "exchange": exchange, "currency": meta["currency"], "company": meta.get("longName") or meta.get("shortName")})
        except Exception as exc:
            if getattr(exc, "code", None) in {403, 429}:
                raise
    symbol = matches[0]["symbol"] if len(matches) == 1 else None
    charts.write_json(path, {"ticker": row["ticker"], "symbol": symbol, "matches": matches, "queried_at": datetime.now(timezone.utc).isoformat()})
    return symbol


def fetch(row):
    statements, errors = [], []
    symbol = resolve_yahoo(row)
    if symbol:
        params = {"type": ",".join(prefix + field for prefix in ("annual", "quarterly") for field in info.METRICS.values()),
                  "period1": 1719792000, "period2": 1735689600}
        try:
            payload = info.fetch_json(f"https://query1.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/{quote(symbol, safe='')}?{urlencode(params)}")
            statements = info.parse_yahoo_financials(payload, symbol, END)
        except Exception as exc:
            if getattr(exc, "code", None) in {403, 429}:
                raise
            errors.append(f"Yahoo: {type(exc).__name__}: {exc}")
    else:
        errors.append("Exact Yahoo listing unavailable; existing original statements retained")
    # Naver annual reports can supply Korean FY2024 even when Yahoo has no data.
    if row["market"] == "korea" and not any(s.get("revenue") is not None and s.get("operating_income") is not None for s in statements):
        try:
            payload = info.fetch_json(f"https://m.stock.naver.com/api/stock/{row['ticker'][:6]}/finance/annual")
            fallback = info.parse_naver_financials(payload, "annual", END)
            keys = {(s["type"], s["period_end"]) for s in statements}
            statements += [s for s in fallback if (s["type"], s["period_end"]) not in keys]
        except Exception as exc:
            if getattr(exc, "code", None) in {403, 429}:
                raise
            errors.append(f"Naver: {type(exc).__name__}: {exc}")
    return [s for s in statements if START <= s["period_end"] <= END], errors


def merge(previous, statements, checked_at):
    result = dict(previous)
    # Same provider's old period may contain more metrics; merge only within
    # an identical period, reporting currency and source. Never mix currencies.
    merged = {(s["type"], s["period_end"], s["currency"]): dict(s) for s in previous.get("financials", [])}
    for statement in statements:
        key = statement["type"], statement["period_end"], statement["currency"]
        old = merged.get(key)
        if old and old.get("source") == statement.get("source"):
            merged[key] = {**old, **{k: v for k, v in statement.items() if v is not None}}
        elif not old:
            merged[key] = statement
    result["financials"] = sorted(merged.values(), key=lambda s: (s["period_end"], s["type"], s["currency"]))
    dates = [s["period_end"] for s in result["financials"]]
    historical = [s for s in result["financials"] if START <= s["period_end"] <= END]
    result.update(requested_start=START, historical_2024_h2_fetched_at=checked_at,
                  historical_2024_h2_coverage={"start": START, "end": END, "periods": len(historical),
                    "annual_periods": sum(s["type"] == "annual" for s in historical),
                    "quarterly_periods": sum(s["type"] == "quarterly" for s in historical),
                    "note": "확인된 확정 실적만 표시합니다. 연간 실적은 해당 회계연도 전체이며, 미제공 분기는 추정하지 않습니다."})
    result["financial_coverage"] = {**previous.get("financial_coverage", {}), "first_period": min(dates, default=None), "latest_period": max(dates, default=None)}
    return result


def fetch_with_current(row, scanner):
    statements, errors = fetch(row)
    current = info.collect_one(row, scanner, datetime.now(timezone.utc).date().isoformat()) if scanner is not None else None
    if current and current.get("rate_limited"):
        raise RuntimeError("Source access limited; checkpoint saved")
    return statements, errors, current


def checkpoint(db, rows):
    values = {ticker: json.loads(raw) for ticker, raw in db.execute("SELECT ticker,value FROM financial_2024_h2_updates")}
    results = [{**row, **values.get(row["ticker"], {"status": "pending"})} for row in rows]
    charts.write_json(AUDIT / "financial-results.json", results)
    charts.write_json(AUDIT / "financial-progress.json", {
        "requested_start": START, "requested_end": END, "total": len(rows), "checked": len(values),
        "pending": sum(r["status"] == "pending" for r in results), "counts": dict(Counter(r["status"] for r in results)),
        "last_checked": max((r for r in results if r["status"] != "pending"), key=lambda r: r["queried_at"], default=None),
        "next": next((r for r in results if r["status"] == "pending"), None),
        "resume": "python -u scripts/backfill_stock_information_2024_h2.py collect",
        "queried_at": datetime.now(timezone.utc).isoformat()})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["collect", "audit", "export"])
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--retry-errors", action="store_true")
    parser.add_argument("--market")
    parser.add_argument("--only-unavailable", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.workers <= 12:
        parser.error("workers must be 1-12")
    db = info.open_database(STATE)
    db.execute("CREATE TABLE IF NOT EXISTS financial_2024_h2_updates(ticker TEXT PRIMARY KEY,value TEXT NOT NULL)")
    rows = charts.roster()
    if args.mode == "export":
        info.export(db)
        mappings = [json.loads(path.read_text(encoding="utf-8")) for path in sorted((STATE / "mappings").glob("*.json"))]
        charts.write_json(AUDIT / "listing-mappings.json", {"schema_version": 1, "start": START, "end": END, "listings": mappings})
    elif args.mode == "collect":
        complete = {ticker for ticker, raw in db.execute("SELECT ticker,value FROM financial_2024_h2_updates") if not args.retry_errors or not json.loads(raw).get("errors")}
        pending = [row for row in rows if row["ticker"] not in complete]
        if args.only_unavailable:
            unavailable = {ticker for ticker, raw in db.execute("SELECT ticker,value FROM financial_2024_h2_updates") if json.loads(raw)["status"] == "unavailable"}
            pending = [row for row in rows if row["ticker"] in unavailable]
        if args.market:
            pending = [row for row in pending if row["market"] == args.market]
        if args.limit is not None:
            pending = pending[:args.limit]
        existing = {ticker for ticker, in db.execute("SELECT ticker FROM information")}
        new = [row for row in pending if row["ticker"] not in existing]
        if new:
            info.scan(db, new, datetime.now(timezone.utc).date().isoformat())
        scanners = {ticker: json.loads(raw) for ticker, raw in db.execute("SELECT ticker,value FROM scanner") if ticker not in existing}
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            for start in range(0, len(pending), 40):
                batch = pending[start:start + 40]
                futures = [pool.submit(fetch_with_current, row, scanners.get(row["ticker"])) for row in batch]
                for row, future in zip(batch, futures):
                    try:
                        statements, errors, current = future.result()
                    except Exception:
                        checkpoint(db, rows)
                        raise
                    checked_at = datetime.now(timezone.utc).isoformat()
                    stored = db.execute("SELECT value FROM information WHERE ticker=?", (row["ticker"],)).fetchone()
                    if not stored:
                        # New calendar members need a current information lookup
                        # too; do not discard them or borrow another listing.
                        previous = current or {"ticker": row["ticker"], "fetched_at": checked_at, "quote": None, "metrics": {}, "financials": [], "warnings": ["원본 현재 정보 미제공"]}
                    else:
                        previous = json.loads(stored[0])
                    value = merge(previous, statements, checked_at)
                    coverage = value["historical_2024_h2_coverage"]
                    result = {"queried_at": checked_at, "status": "available" if coverage["periods"] else "unavailable", **coverage, "errors": errors}
                    db.execute("INSERT OR REPLACE INTO information VALUES (?,?)", (row["ticker"], json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)))
                    db.execute("INSERT OR REPLACE INTO financial_2024_h2_updates VALUES (?,?)", (row["ticker"], json.dumps(result, ensure_ascii=False)))
                    db.commit()
                checkpoint(db, rows)
                print(f"H2-2024 financials order={batch[-1]['order']}/{len(rows)} {batch[-1]['ticker']}", flush=True)
    checkpoint(db, rows)
    db.close()


if __name__ == "__main__":
    main()
