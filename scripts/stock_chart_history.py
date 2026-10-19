"""Resume a sequential, per-stock audit of real daily chart history and publish compact snapshots."""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import ExitStack
import csv
from datetime import date, datetime, timedelta, timezone
import gzip
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import time
import re
from urllib.parse import quote, urlencode
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from generate_semiconductor_data import classified_seeds, fetch_json

ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "data/chart-audit"
PACKS = ROOT / "data/stock-history"
DATABASE = ROOT / "data/tmp_chart_audit/history.sqlite"
MARKETS = ["korea", "us", "japan", "taiwan", "china", "europe", "hongkong"]


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n", encoding="utf-8")
    for attempt in range(10):
        try:
            temporary.replace(path)
            break
        except PermissionError:
            if attempt == 9:
                raise
            time.sleep(0.02 * (attempt + 1))


def roster() -> list[dict]:
    rows = {}
    for kind in ("new-highs", "turnover"):
        for path in sorted((ROOT / "data" / kind / "reports").rglob("*.json")):
            report = json.loads(path.read_text(encoding="utf-8-sig"))
            for entry in report["entries"]:
                ticker = entry["ticker"].upper()
                previous = rows.get(ticker)
                if previous and previous["date"] > report["date"]:
                    continue
                rows[ticker] = {"ticker": ticker, "name": entry["name"], "market": report["market"],
                                "exchange": entry["exchange"], "date": report["date"], "source": kind, "pages": ["market"]}
    ordered = []
    def append(item: dict, page: str) -> None:
        ticker = item["ticker"]
        row = rows.pop(ticker, {**item, "pages": []})
        row.update({key: item[key] for key in ("name", "exchange", "market") if key in item})
        if page not in row["pages"]:
            row["pages"].append(page)
        existing = next((entry for entry in ordered if entry["ticker"] == ticker), None)
        if existing:
            if page not in existing["pages"]:
                existing["pages"].append(page)
        else:
            ordered.append(row)
    for seed in classified_seeds():
        append({"ticker": seed["ticker"], "name": seed["name"], "market": "korea",
                "exchange": "KOSPI" if seed["ticker"].endswith(".KS") else "KOSDAQ"}, "semiconductor")
    peer_index = ROOT / "frontend/public/data/index.json"
    for stock in json.loads(peer_index.read_text(encoding="utf-8"))["stocks"]:
        ticker = stock["ticker"]
        market = next((market for suffix, market in [(".KS", "korea"), (".KQ", "korea"), (".T", "japan"), (".TW", "taiwan"), (".HK", "hongkong")] if ticker.endswith(suffix)), "us")
        append({"ticker": ticker, "name": stock["name_kr"], "market": market}, "peer")
    ordered.extend(sorted(rows.values(), key=lambda row: (MARKETS.index(row["market"]), row["ticker"])))
    return [{"order": i + 1, **row} for i, row in enumerate(ordered)]


def yahoo_symbol(ticker: str) -> str | None:
    if ":" not in ticker:
        symbol = ticker.replace("/", "-")
        return symbol if re.search(r"\.(KS|KQ|T|TW|TWO|SS|SZ|HK|DE|L|SW|PA|AS|BR|LS)$", symbol) else symbol.replace(".", "-")
    exchange, code = ticker.split(":", 1)
    suffix = {"XETR": ".DE", "XETRA": ".DE", "LSE": ".L", "SIX": ".SW"}.get(exchange)
    return code + suffix if suffix else None


def parse_yahoo(payload: dict, ticker: str) -> dict:
    result = payload["chart"]["result"][0]
    meta = result["meta"]
    if meta.get("symbol", "").upper() != yahoo_symbol(ticker) or meta.get("instrumentType") not in {"EQUITY", "ETF", "MUTUALFUND"}:
        raise ValueError("Yahoo symbol or listed instrument identity mismatch")
    zone = ZoneInfo(meta["exchangeTimezoneName"])
    indicators = result["indicators"]
    closes = indicators["quote"][0]["close"]
    adjusted = (indicators.get("adjclose") or [{}])[0].get("adjclose", [])
    prices = []
    for i, stamp in enumerate(result.get("timestamp", [])):
        close = closes[i]
        if type(close) not in (int, float) or not math.isfinite(close) or close <= 0:
            continue
        day = datetime.fromtimestamp(stamp, zone).date().isoformat()
        adj = adjusted[i] if i < len(adjusted) and type(adjusted[i]) in (int, float) and math.isfinite(adjusted[i]) and adjusted[i] > 0 else close
        prices.append([day, close, adj])
    first_trade = meta.get("firstTradeDate")
    return {"ticker": ticker, "currency": meta["currency"], "source": "Yahoo Finance daily chart",
            "fetched_at": datetime.fromtimestamp(meta.get("regularMarketTime", 0), timezone.utc).isoformat(),
            "provider_date": datetime.fromtimestamp(meta.get("regularMarketTime", 0), zone).date().isoformat(),
            "first_trade_date": (datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=first_trade)).astimezone(zone).date().isoformat() if first_trade else None,
            "prices": prices}


def parse_tradingview(payload: dict, ticker: str) -> dict:
    info = payload["info"]
    exchange, code = ticker.split(":", 1)
    cboe = (exchange in {"NASDAQ", "NYSE", "AMEX"} and info.get("source_id") == "BATS"
            and info.get("name") == code and info.get("full_name") == f"BATS:{code}"
            and info.get("currency_code") == "USD" and info.get("type") == "stock")
    if payload["symbol"] != ticker or info["pro_name"] != ticker or not (info["source_id"] == exchange or cboe):
        raise ValueError("TradingView listing identity mismatch")
    if info.get("type") in {"index", "forex", "crypto", "futures", "bond", "economic"}:
        raise ValueError("TradingView instrument is not a stock")
    zone = ZoneInfo(info["timezone"])
    prices = [[datetime.fromtimestamp(bar["timestamp"], zone).date().isoformat(), bar["close"], bar["close"]]
              for bar in payload["bars"] if bar["close"] > 0]
    return {"ticker": ticker, "currency": info["currency_code"], "source": "TradingView · Cboe One split-adjusted daily chart" if cboe else "TradingView split-adjusted daily chart",
            "fetched_at": payload.get("fetched_at"), "first_trade_date": None,
            "requested_bars": payload.get("requested_bars"), "prices": prices}


def database() -> sqlite3.Connection:
    DATABASE.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DATABASE)
    db.execute("CREATE TABLE IF NOT EXISTS history (ticker TEXT PRIMARY KEY, value TEXT NOT NULL)")
    db.execute("CREATE TABLE IF NOT EXISTS imported (path TEXT PRIMARY KEY)")
    if not db.execute("SELECT count(*) FROM history").fetchone()[0]:
        for path in sorted(PACKS.glob("*.json.gz")):
            values = json.loads(gzip.decompress(path.read_bytes()))
            db.executemany("INSERT OR REPLACE INTO history VALUES (?,?)", [(ticker, json.dumps(value, ensure_ascii=False, separators=(",", ":"))) for ticker, value in values.items()])
        db.commit()
    return db


def quality(value: dict) -> tuple:
    prices = value["prices"]
    if not prices:
        return (False, "", 0)
    span = (date.fromisoformat(prices[-1][0]) - date.fromisoformat(prices[0][0])).days
    return (span >= 365, prices[-1][0], len(prices))


def save_candidate(db: sqlite3.Connection, value: dict) -> None:
    if not value["prices"]:
        return
    dates = [point[0] for point in value["prices"]]
    if dates != sorted(set(dates)):
        raise ValueError("Daily history contains duplicate or unordered sessions")
    previous = db.execute("SELECT value FROM history WHERE ticker=?", (value["ticker"],)).fetchone()
    if previous:
        old = json.loads(previous[0])
        verified_full_request = value.get("requested_range") in {"2y", "5y", "10y", "max"} or (value.get("requested_bars") or 0) >= 366
        def fetched_time(item):
            try:
                timestamp = datetime.fromisoformat(item.get("fetched_at") or "")
                return timestamp.replace(tzinfo=timestamp.tzinfo or timezone.utc).timestamp()
            except (TypeError, ValueError):
                return 0
        newer_full_request = verified_full_request and value["prices"][-1][0] >= old["prices"][-1][0] and fetched_time(value) >= fetched_time(old)
        if not newer_full_request and quality(old) >= quality(value):
            return
    db.execute("INSERT OR REPLACE INTO history VALUES (?,?)", (value["ticker"], json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)))


def import_caches(db: sqlite3.Connection, rows: list[dict], limit: int | None) -> None:
    known = {row["ticker"] for row in rows}
    mapping = {symbol: row["ticker"] for row in rows if (symbol := yahoo_symbol(row["ticker"]))}
    imported = {row[0] for row in db.execute("SELECT path FROM imported")}
    paths = sorted((ROOT / "data/tmp_tradingview_chart/1D").glob("*.json")) + sorted((ROOT / "data/tmp_calendar_history/1d-dated").glob("*.json"))
    done = 0
    for path in paths:
        relative = path.relative_to(ROOT).as_posix()
        if relative in imported:
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if "symbol" in payload:
                ticker = payload["symbol"]
                if ticker in known:
                    save_candidate(db, parse_tradingview(payload, ticker))
            else:
                symbol = payload["chart"]["result"][0]["meta"]["symbol"].upper()
                if symbol in mapping:
                    save_candidate(db, parse_yahoo(payload, mapping[symbol]))
        except (KeyError, ValueError, TypeError, IndexError):
            pass  # Unknown instruments never become an apparently valid daily history.
        db.execute("INSERT OR IGNORE INTO imported VALUES (?)", (relative,))
        done += 1
        if done % 500 == 0:
            db.commit()
            write_json(AUDIT / "progress.json", {"phase": "importing_caches", "imported_files": len(imported) + done,
                       "cache_files": len(paths), "candidates": db.execute("SELECT count(*) FROM history").fetchone()[0],
                       "resume": "python scripts/stock_chart_history.py import-caches"})
            print(f"Cache files {len(imported) + done}/{len(paths)}", flush=True)
        if limit and done >= limit:
            break
    db.commit()


def assessment(value: dict | None, as_of: date) -> str:
    if not value or len(value["prices"]) < 2:
        return "missing"
    cutoff = as_of.replace(year=as_of.year - 1) if (as_of.month, as_of.day) != (2, 29) else date(as_of.year - 1, 2, 28)
    if value["prices"][-1][0] < (as_of - timedelta(days=7)).isoformat():
        recent_query = str(value.get("fetched_at") or "")[:10] >= (as_of - timedelta(days=1)).isoformat()
        if recent_query and (value.get("requested_range") in {"2y", "5y", "10y", "max"} or (value.get("requested_bars") or 0) >= 366) and value.get("provider_date", "") <= value["prices"][-1][0]:
            return "no_recent_data"
        return "stale"
    if value["prices"][0][0] <= cutoff.isoformat():
        return "complete"
    if value.get("first_trade_date") and value["first_trade_date"] > cutoff.isoformat():
        return "short_listing"
    if value.get("requested_range") in {"2y", "5y", "10y", "max"} or (value.get("requested_bars") or 0) >= 366:
        return "limited_history"
    return "insufficient"


def fetch_live_history(row: dict) -> dict:
    """Use the deployed same-listing Yahoo/TradingView adapter; no local websocket dependency."""
    body = json.dumps({"kind": "history", "stocks": [{"ticker": row["ticker"], "exchange": row.get("exchange", "")}]}).encode()
    request = Request("https://find-peer-stock-live-api.find-peer-stock-juyeop.workers.dev/refresh", data=body,
                      headers={"Content-Type": "application/json", "Origin": "https://juyeop-dev.github.io", "User-Agent": "Mozilla/5.0"}, method="POST")
    with urlopen(request, timeout=45) as response:
        payload = json.load(response)
    item = payload["items"][0]
    if item["ticker"] != row["ticker"] or not item["currency"]:
        raise ValueError("Live history listing identity mismatch")
    prices = [[point["date"], point["close"], point["adjusted_close"]] for point in item["history"]]
    return {"ticker": row["ticker"], "currency": item["currency"], "source": item["source"],
            "fetched_at": item["fetched_at"], "first_trade_date": item.get("first_trade_date"),
            "provider_date": prices[-1][0], "requested_range": "2y", "prices": prices}


def audit(db: sqlite3.Connection, rows: list[dict], as_of: date, fetch_missing: bool, limit: int | None, via_api: bool = False) -> None:
    previous = {}
    log = AUDIT / "results.jsonl"
    if log.exists():
        previous = {item["ticker"]: item for line in log.read_text(encoding="utf-8").splitlines() if (item := json.loads(line))}
    counts, done, attempted = Counter(), 0, 0
    stopped_for_source = False
    AUDIT.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as journal:
        for row in rows:
            did_fetch = False
            stored = db.execute("SELECT value FROM history WHERE ticker=?", (row["ticker"],)).fetchone()
            value = json.loads(stored[0]) if stored else None
            status = assessment(value, as_of)
            error = previous.get(row["ticker"], {}).get("error") if status in {"missing", "stale", "insufficient"} else None
            if fetch_missing and status in {"missing", "stale", "insufficient"}:
                if limit is not None and attempted >= limit:
                    break
                attempted += 1
                did_fetch = True
                try:
                    symbol = yahoo_symbol(row["ticker"])
                    if via_api:
                        value = fetch_live_history(row)
                    elif symbol:
                        value = parse_yahoo(fetch_json(f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol, safe='')}?range=2y&interval=1d"), row["ticker"])
                        value["requested_range"] = "2y"
                        value["fetched_at"] = datetime.now(timezone.utc).isoformat()
                    else:
                        from quote_sources.tradingview_chart import fetch_chart
                        value = parse_tradingview(fetch_chart(row["ticker"], "1D", 550), row["ticker"])
                    save_candidate(db, value)
                    db.commit()
                    status = assessment(value, as_of)
                except Exception as exc:
                    error = f"{type(exc).__name__}: {exc}"
                    stopped_for_source = isinstance(exc, HTTPError) and exc.code in {403, 429}
            result = {**row, "status": status, "as_of": as_of.isoformat(), "checked_at": datetime.now(timezone.utc).isoformat(),
                      "start": value["prices"][0][0] if value and value["prices"] else None,
                      "end": value["prices"][-1][0] if value and value["prices"] else None,
                      "points": len(value["prices"]) if value else 0, "error": error,
                      "currency": value.get("currency") if value else None,
                      "history_source": value.get("source") if value else None,
                      "first_trade_date": value.get("first_trade_date") if value else None}
            journal.write(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n")
            journal.flush()
            done += 1
            counts[status] += 1
            if did_fetch or done % 50 == 0:
                write_json(AUDIT / "progress.json", {"phase": "auditing", "as_of": as_of.isoformat(), "total": len(rows),
                           "checked": done, "counts": dict(counts), "last": row, "resume": "python scripts/stock_chart_history.py refresh-batches --limit 1000"})
            if did_fetch or done % 500 == 0:
                print(f"{done}/{len(rows)} {row['ticker']} {status}" + (f" {error}" if error else ""), flush=True)
            if stopped_for_source:
                break
    write_json(AUDIT / "progress.json", {"phase": "source_access_limited" if stopped_for_source else "audit_finished", "as_of": as_of.isoformat(), "total": len(rows),
               "checked": done, "counts": dict(counts), "resume": "python scripts/stock_chart_history.py repair --pending-only --limit 100"})


def export_packs(db: sqlite3.Connection) -> None:
    PACKS.mkdir(parents=True, exist_ok=True)
    counts = Counter()
    with ExitStack() as stack:
        writers = {}
        for shard in "0123456789abcdef":
            handle = stack.enter_context((PACKS / f"{shard}.json.gz.tmp").open("wb"))
            writer = stack.enter_context(gzip.GzipFile(fileobj=handle, mode="wb", filename="", mtime=0, compresslevel=9))
            writer.write(b"{"); writers[shard] = writer
        for ticker, raw in db.execute("SELECT ticker,value FROM history ORDER BY ticker"):
            shard = hashlib.sha256(ticker.encode()).hexdigest()[0]
            if counts[shard]: writers[shard].write(b",")
            writers[shard].write(json.dumps(ticker).encode() + b":" + raw.encode("utf-8"))
            counts[shard] += 1
        for writer in writers.values(): writer.write(b"}")
    for shard in writers:
        temporary = PACKS / f"{shard}.json.gz.tmp"
        target = PACKS / f"{shard}.json.gz"
        if target.exists() and temporary.read_bytes() == target.read_bytes():
            temporary.unlink()
        else:
            temporary.replace(target)
    print(f"Exported {sum(counts.values())} stock histories")


def checkpoint(rows: list[dict]) -> None:
    log = AUDIT / "results.jsonl"
    latest = {item["ticker"]: item for line in log.read_text(encoding="utf-8").splitlines() if (item := json.loads(line))}
    results = [{**latest.get(row["ticker"], {"status": "pending"}), **row} for row in rows]
    temporary = log.with_suffix(".jsonl.tmp")
    with temporary.open("w", encoding="utf-8") as output:
        for result in results:
            output.write(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n")
    temporary.replace(log)
    fields = ["order", "ticker", "name", "market", "status", "start", "end", "points", "currency", "history_source", "first_trade_date", "error"]
    with (AUDIT / "results.csv").open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
        writer.writeheader(); writer.writerows(results)
    pending = [row for row in results if row["status"] in {"missing", "stale", "insufficient", "pending"}]
    write_json(AUDIT / "pending.json", pending)
    write_json(AUDIT / "progress.json", {"phase": "source_exceptions_remaining" if pending else "audited",
               "as_of": results[0].get("as_of") if results else None,
               "total": len(rows), "checked": len(results), "counts": dict(Counter(row["status"] for row in results)),
               "pending_count": len(pending), "next": pending[0] if pending else None,
               "resume": "python scripts/stock_chart_history.py repair --pending-only --limit 100",
               "updated_at": datetime.now(timezone.utc).isoformat()})


def refresh_batches(db: sqlite3.Connection, rows: list[dict], as_of: date, limit: int | None) -> None:
    """Fetch at most 20 symbols per request, then journal each in the original order."""
    log = AUDIT / "results.jsonl"
    latest = {item["ticker"]: item for line in log.read_text(encoding="utf-8").splitlines() if (item := json.loads(line))} if log.exists() else {}
    pending = []
    for row in rows:
        stored = db.execute("SELECT value FROM history WHERE ticker=?", (row["ticker"],)).fetchone()
        if assessment(json.loads(stored[0]) if stored else None, as_of) in {"missing", "stale", "insufficient"}:
            pending.append(row)
    if limit is not None:
        pending = pending[:limit]
    processed = 0
    with log.open("a", encoding="utf-8") as journal:
        cursor = 0
        while cursor < len(pending):
            batch = []
            while cursor < len(pending) and len(batch) < 20:
                row = pending[cursor]
                if not yahoo_symbol(row["ticker"]) and batch:
                    break
                batch.append(row); cursor += 1
                if not yahoo_symbol(row["ticker"]):
                    break
            values, errors = {}, {}
            rate_limited = False
            try:
                if yahoo_symbol(batch[0]["ticker"]):
                    symbols = ",".join(yahoo_symbol(row["ticker"]) for row in batch)
                    response = fetch_json("https://query1.finance.yahoo.com/v7/finance/spark?" + urlencode({"symbols": symbols, "range": "2y", "interval": "1d"}))
                    returned = {result["symbol"].upper(): result for result in response.get("spark", {}).get("result", [])}
                    for row in batch:
                        ticker = row["ticker"]
                        try:
                            result = returned[yahoo_symbol(ticker)]["response"][0]
                            value = parse_yahoo({"chart": {"result": [result]}}, ticker)
                            value["source"] = "Yahoo Finance daily chart (spark)"
                            value["requested_range"] = "2y"
                            value["fetched_at"] = datetime.now(timezone.utc).isoformat()
                            values[ticker] = value
                        except (KeyError, ValueError, IndexError, TypeError) as exc:
                            errors[ticker] = f"No matching daily series: {type(exc).__name__}"
                else:
                    ticker = batch[0]["ticker"]
                    values[ticker] = fetch_live_history(batch[0])
            except Exception as exc:
                rate_limited = isinstance(exc, HTTPError) and exc.code == 429 or "rate limit" in str(exc).lower()
                errors = {row["ticker"]: str(exc) for row in batch}
            for row in batch:
                ticker = row["ticker"]
                value = values.get(ticker)
                if value:
                    save_candidate(db, value)
                    db.commit()
                else:
                    stored = db.execute("SELECT value FROM history WHERE ticker=?", (ticker,)).fetchone()
                    value = json.loads(stored[0]) if stored else None
                result = {**row, "as_of": as_of.isoformat(), "status": assessment(value, as_of),
                          "start": value["prices"][0][0] if value and value["prices"] else None,
                          "end": value["prices"][-1][0] if value and value["prices"] else None,
                          "points": len(value["prices"]) if value else 0, "error": errors.get(ticker),
                          "checked_at": datetime.now(timezone.utc).isoformat()}
                latest[ticker] = result
                journal.write(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n"); journal.flush()
                processed += 1
            db.commit()
            counts = Counter(row["status"] for row in latest.values())
            write_json(AUDIT / "progress.json", {"phase": "rate_limited" if rate_limited else "refreshing_sequentially",
                       "as_of": as_of.isoformat(), "total": len(rows), "counts": dict(counts), "last": batch[-1],
                       "processed_this_run": processed, "remaining_this_run": len(pending) - processed,
                       "resume": "python scripts/stock_chart_history.py refresh-batches --limit 1000"})
            print(f"Refreshed {processed}/{len(pending)}; last #{batch[-1]['order']} {batch[-1]['ticker']}; {dict(counts)}", flush=True)
            if rate_limited:
                print("Provider rate limit: checkpoint saved; stop until a later request.", flush=True)
                break


def publish(output: Path = ROOT / "frontend/public/data/stock-history") -> int:
    count = 0
    for path in sorted(PACKS.glob("*.json.gz")):
        for ticker, value in json.loads(gzip.decompress(path.read_bytes())).items():
            filename = quote(ticker, safe="").replace("%", "~")
            write_json(output / f"{filename}.json", value)
            count += 1
    print(f"Published {count} continuous daily stock histories")
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["prepare", "import-caches", "audit", "repair", "refresh-batches", "checkpoint", "export", "publish"])
    parser.add_argument("--limit", type=int)
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--pending-only", action="store_true", help="Repair only the saved unfinished symbols; retain the rest of this audit baseline.")
    parser.add_argument("--as-of", type=date.fromisoformat, default=datetime.now(ZoneInfo("Asia/Seoul")).date())
    args = parser.parse_args()
    if args.mode == "publish":
        publish()
        return
    rows = roster()
    write_json(AUDIT / "roster.json", rows)
    db = database()
    if args.mode in {"prepare", "import-caches"}:
        source = json.loads((ROOT / "data/semiconductor/index.json").read_text(encoding="utf-8"))
        for stock in source["stocks"]:
            save_candidate(db, {"ticker": stock["ticker"], "currency": "KRW", "source": source["history_source"],
                           "fetched_at": source["generated_at"], "first_trade_date": None,
                           "prices": [[p["date"], p["close"], p["adjusted_close"]] for p in stock["history"]]})
        db.commit()
        if args.mode == "import-caches":
            import_caches(db, rows, args.limit)
    elif args.mode == "audit":
        audit(db, rows, args.as_of, args.fetch, args.limit)
    elif args.mode == "repair":
        targets = rows
        if args.pending_only:
            symbols = {row["ticker"] for row in json.loads((AUDIT / "pending.json").read_text(encoding="utf-8"))}
            targets = [row for row in rows if row["ticker"] in symbols]
        audit(db, targets, args.as_of, True, args.limit, via_api=True)
        if args.pending_only:
            checkpoint(rows)
    elif args.mode == "refresh-batches":
        refresh_batches(db, rows, args.as_of, args.limit)
    elif args.mode == "checkpoint":
        checkpoint(rows)
    elif args.mode == "export":
        export_packs(db)
    db.close()


if __name__ == "__main__":
    main()
