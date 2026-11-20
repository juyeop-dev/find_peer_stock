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
from contextlib import closing

import stock_chart_history as charts
import stock_information as info

from dataclasses import replace
from pathlib import Path
from financial_history_request import financial_request


def default_request():
    return financial_request(year=2024, half=2, root=info.ROOT)


def require_source_access(error):
    """Do not record sandbox/network permission failures as unavailable data."""
    reason = getattr(error, "reason", error)
    if getattr(error, "code", None) in {403, 429} or getattr(reason, "winerror", None) == 10013 or "WinError 10013" in str(reason):
        raise error


@cache
def european_listings():
    path = info.ROOT / "data/tmp_tradingview_chart/universe.json"
    return {row["symbol"]: row for row in json.loads(path.read_text(encoding="utf-8"))["rows"]} if path.exists() else {}


def resolve_yahoo(row, request=None):
    request = request or default_request()
    if symbol := charts.yahoo_symbol(row["ticker"]):
        return symbol
    if not row["ticker"].startswith("EURONEXT:"):
        return None
    listing = european_listings().get(row["ticker"])
    if not listing:
        return None
    path = request.state / "mappings" / (hashlib.sha256(row["ticker"].encode()).hexdigest() + ".json")
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
            require_source_access(exc)
    symbol = matches[0]["symbol"] if len(matches) == 1 else None
    charts.write_json(path, {"ticker": row["ticker"], "symbol": symbol, "matches": matches, "queried_at": datetime.now(timezone.utc).isoformat()})
    return symbol


def fetch(row, request=None):
    request = request or default_request()
    statements, errors = [], []
    symbol = resolve_yahoo(row, request)
    if symbol:
        params = {"type": ",".join(prefix + field for prefix in ("annual", "quarterly") for field in info.METRICS.values()),
                  "period1": int(datetime.fromisoformat(request.start).replace(tzinfo=timezone.utc).timestamp()),
                  "period2": int(datetime.fromisoformat(request.end).replace(tzinfo=timezone.utc).timestamp()) + 86400}
        try:
            payload = info.fetch_json(f"https://query1.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/{quote(symbol, safe='')}?{urlencode(params)}")
            statements = info.parse_yahoo_financials(payload, symbol, request.end, start=request.start)
        except Exception as exc:
            require_source_access(exc)
            errors.append(f"Yahoo: {type(exc).__name__}: {exc}")
    else:
        errors.append("Exact Yahoo listing unavailable; existing original statements retained")
    # Naver annual reports can supply Korean FY2024 even when Yahoo has no data.
    if row["market"] == "korea" and not any(s.get("revenue") is not None and s.get("operating_income") is not None for s in statements):
        try:
            payload = info.fetch_json(f"https://m.stock.naver.com/api/stock/{row['ticker'][:6]}/finance/annual")
            fallback = info.parse_naver_financials(payload, "annual", request.end, start=request.start)
            keys = {(s["type"], s["period_end"]) for s in statements}
            statements += [s for s in fallback if (s["type"], s["period_end"]) not in keys]
        except Exception as exc:
            require_source_access(exc)
            errors.append(f"Naver: {type(exc).__name__}: {exc}")
    return [s for s in statements if request.start <= s["period_end"] <= request.end], errors


def merge(previous, statements, checked_at, request=None):
    request = request or default_request()
    result = dict(previous)
    result["requested_start"] = min(previous.get("requested_start", request.start), request.start)
    # Same provider's old period may contain more metrics; merge only within
    # an identical period, reporting currency and source. Never mix currencies.
    merged = {(s["type"], s["period_end"], s["currency"]): dict(s) for s in previous.get("financials", [])}
    for statement in statements:
        if not request.start <= statement["period_end"] <= request.end:
            continue
        key = statement["type"], statement["period_end"], statement["currency"]
        old = merged.get(key)
        if old and old.get("source") == statement.get("source"):
            merged[key] = {**old, **{k: v for k, v in statement.items() if v is not None}}
        elif old and all(old.get(metric) is None or statement.get(metric) is not None for metric in info.METRICS) and sum(statement.get(metric) is not None for metric in info.METRICS) > sum(old.get(metric) is not None for metric in info.METRICS):
            merged[key] = statement
        elif not old:
            merged[key] = statement
    result["financials"] = sorted(merged.values(), key=lambda s: (s["period_end"], s["type"], s["currency"]))
    dates = [s["period_end"] for s in result["financials"]]
    historical = [s for s in result["financials"] if request.start <= s["period_end"] <= request.end]
    result.update({request.fetched_key: checked_at,
                  request.coverage_key: {"start": request.start, "end": request.end, "periods": len(historical),
                    "annual_periods": sum(s["type"] == "annual" for s in historical),
                    "quarterly_periods": sum(s["type"] == "quarterly" for s in historical),
                    "note": "확인된 확정 실적만 표시합니다. 연간 실적은 해당 회계연도 전체이며, 미제공 분기는 추정하지 않습니다."}})
    result["financial_coverage"] = {**previous.get("financial_coverage", {}), "first_period": min(dates, default=None), "latest_period": max(dates, default=None)}
    return result


def fetch_with_current(row, scanner, request=None):
    request = request or default_request()
    statements, errors = fetch(row, request)
    current = info.collect_one(row, scanner, datetime.now(timezone.utc).date().isoformat(), start=request.start) if scanner is not None else None
    if current and current.get("rate_limited"):
        raise RuntimeError("Source access limited; checkpoint saved")
    return statements, errors, current


def checkpoint(db, rows, request=None):
    request = request or default_request()
    values = {ticker: json.loads(raw) for ticker, raw in db.execute(f"SELECT ticker,value FROM {request.table}")}
    results = [{**row, **values.get(row["ticker"], {"status": "pending"})} for row in rows]
    charts.write_json(request.audit / "financial-results.json", results)
    charts.write_json(request.audit / "financial-progress.json", {
        "requested_start": request.start, "requested_end": request.end, "total": len(rows), "checked": len(values),
        "pending": sum(r["status"] == "pending" for r in results), "counts": dict(Counter(r["status"] for r in results)),
        "last_checked": max((r for r in results if r["status"] != "pending"), key=lambda r: r["queried_at"], default=None),
        "next": next((r for r in results if r["status"] == "pending"), None),
        "resume": request.resume,
        "queried_at": datetime.now(timezone.utc).isoformat()})


def main(argv=None, *, request=None, rows=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["collect", "audit", "export"])
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--retry-errors", action="store_true")
    parser.add_argument("--market")
    parser.add_argument("--only-unavailable", action="store_true")
    parser.add_argument("--history-config", type=Path)
    parser.add_argument("--year", type=int)
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.history_config is not None or args.year is not None:
            from history_policy import DEFAULT_POLICY
            request = financial_request(year=args.year, config=args.history_config or DEFAULT_POLICY, root=info.ROOT)
        else:
            request = request or default_request()
        if args.state_dir is not None:
            request = replace(request, state=args.state_dir)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    resume = request.resume
    for name in ["history_config", "state_dir", "year", "workers", "limit", "market"]:
        value = getattr(args, name)
        if value is not None:
            resume += ' --' + name.replace('_', '-') + ' "' + str(value).replace('\\', '/') + '"'
    for name in ["retry_errors", "only_unavailable"]:
        if getattr(args, name):
            resume += ' --' + name.replace('_', '-')
    request = replace(request, resume=resume)
    if not 1 <= args.workers <= 12:
        parser.error("workers must be 1-12")
    if args.limit is not None and args.limit < 0:
        parser.error("limit must be nonnegative")
    if args.dry_run:
        from dataclasses import asdict
        print(json.dumps(asdict(request), default=str))
        return
    with closing(info.open_database(request.state)) as db:
        db.execute(f"CREATE TABLE IF NOT EXISTS {request.table}(ticker TEXT PRIMARY KEY,value TEXT NOT NULL)")
        rows = charts.roster() if rows is None else rows
        if args.mode == "export":
            info.export(db)
            mappings = [json.loads(path.read_text(encoding="utf-8")) for path in sorted((request.state / "mappings").glob("*.json"))]
            charts.write_json(request.audit / "listing-mappings.json", {"schema_version": 1, "start": request.start, "end": request.end, "listings": mappings})
        elif args.mode == "collect":
            complete = {ticker for ticker, raw in db.execute(f"SELECT ticker,value FROM {request.table}")
                        if (saved := json.loads(raw)).get("end") == request.end
                        and (not args.retry_errors or not saved.get("errors"))}
            pending = [row for row in rows if row["ticker"] not in complete]
            if args.only_unavailable:
                unavailable = {ticker for ticker, raw in db.execute(f"SELECT ticker,value FROM {request.table}") if json.loads(raw)["status"] == "unavailable"}
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
                for start in range(0, len(pending), 120):
                    batch = pending[start:start + 120]
                    futures = [pool.submit(fetch_with_current, row, scanners.get(row["ticker"]), request) for row in batch]
                    for row, future in zip(batch, futures):
                        try:
                            statements, errors, current = future.result()
                        except Exception:
                            checkpoint(db, rows, request)
                            raise
                        checked_at = datetime.now(timezone.utc).isoformat()
                        stored = db.execute("SELECT value FROM information WHERE ticker=?", (row["ticker"],)).fetchone()
                        if not stored:
                            # New calendar members need a current information lookup
                            # too; do not discard them or borrow another listing.
                            previous = current or {"ticker": row["ticker"], "fetched_at": checked_at, "quote": None, "metrics": {}, "financials": [], "warnings": ["원본 현재 정보 미제공"]}
                        else:
                            previous = json.loads(stored[0])
                        value = merge(previous, statements, checked_at, request)
                        coverage = value[request.coverage_key]
                        result = {"queried_at": checked_at, "status": "available" if coverage["periods"] else "unavailable", **coverage, "errors": errors, "resume": request.resume}
                        db.execute("INSERT OR REPLACE INTO information VALUES (?,?)", (row["ticker"], json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)))
                        db.execute(f"INSERT OR REPLACE INTO {request.table} VALUES (?,?)", (row["ticker"], json.dumps(result, ensure_ascii=False)))
                        db.commit()
                    checkpoint(db, rows, request)
                    print(f"{request.start}..{request.end} financials order={batch[-1]['order']}/{len(rows)} {batch[-1]['ticker']}", flush=True)
        checkpoint(db, rows, request)


if __name__ == "__main__":
    main()
