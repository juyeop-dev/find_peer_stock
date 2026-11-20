"""Resume original daily prices for the configured historical information range."""
from concurrent.futures import ThreadPoolExecutor
import argparse
import hashlib
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import sys
from urllib.parse import quote, urlencode

import stock_chart_history as charts
import stock_information as information
from history_policy import DEFAULT_POLICY
from price_history_range import load_price_range


def needs_historical_extension(value, request=None):
    request = request or load_price_range()
    prices = value.get("prices") or []
    if not prices:
        return False
    first = value.get("first_trade_date")
    if first and first > request.start:
        if first > request.start[:4] + "-12-31":
            return False
        return prices[0][0] > (date.fromisoformat(first) + timedelta(days=7)).isoformat()
    return prices[0][0] > request.start


def tradingview(row, request=None):
    request = request or load_price_range()
    from quote_sources.tradingview_chart import fetch_chart
    candidates = information.symbols(row)
    if len(candidates) != 1:
        raise ValueError("Exact trading venue unavailable")
    symbol = candidates[0]
    # This adapter returns the latest N bars, not a dated provider range.
    # Include the distance from today even for a completed-year request.
    days = (date.fromisoformat(request.as_of) - date.fromisoformat(request.storage_start())).days
    count = min(5000, max(550, (days * 5 + 6) // 7 + 60))
    payload = fetch_chart(symbol, "1D", count, timeout=15)
    value = request.bound(charts.parse_tradingview(payload, symbol))
    value["ticker"] = row["ticker"]
    value["fetched_at"] = datetime.now(timezone.utc).isoformat()
    value["provider_date"] = value["prices"][-1][0]
    value.update(requested_start=request.storage_start(), requested_end=request.end)
    return value


def fallback(row, mapped_symbol=None, request=None):
    request = request or load_price_range()
    # Spark omits some inactive listings even when their dated chart is still
    # available. Try the same Yahoo listing before the independent TV adapter.
    symbol = charts.yahoo_symbol(row["ticker"]) or mapped_symbol
    if symbol:
        now = datetime.now(timezone.utc)
        start = datetime.fromisoformat(request.storage_start()).replace(tzinfo=timezone.utc)
        # Yahoo's end is exclusive; do not include an extra future day on a
        # request that follows the execution date.
        end = (now if request.end == now.date().isoformat() else
               datetime.fromisoformat(request.end).replace(tzinfo=timezone.utc) + timedelta(days=1))
        params = {"period1": int(start.timestamp()), "period2": int(end.timestamp()), "interval": "1d"}
        try:
            payload = information.fetch_json(f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol, safe='')}?{urlencode(params)}")
            value = request.bound(charts.parse_yahoo(payload, symbol))
            value["ticker"] = row["ticker"]
            value["source_symbol"] = symbol
            if len(value["prices"]) >= 2:
                value.update(fetched_at=now.isoformat(), requested_start=start.date().isoformat(), requested_end=request.end, requested_range="dated")
                return value
        except Exception as exc:
            if getattr(exc, "code", None) in {403, 429}:
                raise
    if row["market"] == "korea":
        # Historical KRX turnover can include merged or delisted companies
        # whose original Korean code still has observed Naver daily bars.
        from backfill_korean_new_highs import cached_request, history_url, parse_history
        now = datetime.now(timezone.utc)
        start, end = date.fromisoformat(request.storage_start()), date.fromisoformat(request.end)
        code = row["ticker"].split(".")[0]
        try:
            bars = parse_history(cached_request(history_url(code, start, end), 18, information.ROOT / "data/tmp_korean_history"),
                                 code=code, start=start, end=end)
            prices = [[day.isoformat(), bar[4], bar[4]] for day, bar in sorted(bars.items()) if bar[4] > 0]
            if len(prices) >= 2:
                return {"ticker": row["ticker"], "currency": "KRW", "source": "Naver Finance adjusted daily history",
                        "source_symbol": f"KRX:{code}", "fetched_at": now.isoformat(), "provider_date": prices[-1][0],
                        "requested_start": start.isoformat(), "requested_end": end.isoformat(), "requested_range": "dated", "prices": prices}
        except Exception as exc:
            if getattr(exc, "code", None) in {403, 429}:
                raise
    return tradingview(row, request)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--retry-errors", action="store_true")
    parser.add_argument("--exclude-market", choices=["korea", "us", "china", "japan", "taiwan", "europe"], help="Process other markets while an independent source cache is still collecting.")
    parser.add_argument("--refresh-tradingview", action="store_true")
    parser.add_argument("--state-dir", type=Path, help="Isolated resumable database directory, initially seeded from published packs.")
    parser.add_argument("--import-europe-cache", action="store_true", help="Reuse the deepest verified same-listing European charts collected by calendar recovery.")
    parser.add_argument("--import-chart-cache", action="store_true", help="Reuse fresh same-listing charts already verified by calendar recovery, preserving confirmed listing dates.")
    parser.add_argument("--extend-to-start", action="store_true", help="Recheck histories that do not reach the configured start, retaining confirmed later listing dates.")
    parser.add_argument("--history-config", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--year", type=int, help="Optional single-year collection request; the original ongoing command remains the default.")
    parser.add_argument("--dry-run", action="store_true", help="Print the resolved range and state without provider or database access.")
    args = parser.parse_args(argv)
    try:
        request = load_price_range(args.history_config, year=args.year)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    table = request.table
    # Keep the existing default audit address. Other ranges cannot overwrite it.
    audit_file = "history-progress.json" if request.scope == "2014" else f"history-{request.scope}-progress.json"
    resume = "python scripts/refresh_stock_information_history.py" + (f' --state-dir "{args.state_dir.as_posix()}"' if args.state_dir else "")
    if args.history_config != DEFAULT_POLICY:
        resume += f' --history-config "{args.history_config.as_posix()}"'
    if args.year is not None:
        resume += f" --year {args.year}"
    for flag in ["retry_errors", "refresh_tradingview", "import_europe_cache", "import_chart_cache", "extend_to_start"]:
        if getattr(args, flag):
            resume += " --" + flag.replace("_", "-")
    if args.exclude_market:
        resume += f" --exclude-market {args.exclude_market}"
    if args.dry_run:
        print(json.dumps({"requested_start": request.start, "requested_end": request.end,
                          "price_reference_start": request.reference_start,
                          "storage_start": request.storage_start(), "state_table": table,
                          "information_database": str((args.state_dir or information.ROOT / "data/tmp_info_update") / "information.sqlite"),
                          "history_database": str(args.state_dir / "history.sqlite" if args.state_dir else charts.DATABASE),
                          "audit": str(information.AUDIT / audit_file), "resume": resume}))
        return
    sys.path.insert(0, str(information.ROOT / "data/tmp_info_update/deps"))
    rows = charts.roster()
    db = information.open_database(args.state_dir)
    db.execute(f"CREATE TABLE IF NOT EXISTS {table}(ticker TEXT PRIMARY KEY,value TEXT NOT NULL)")
    completed = {ticker for ticker, raw in db.execute(f"SELECT ticker,value FROM {table}")
                 if information.fresh((result := json.loads(raw)).get("queried_at"), hours=20)
                 and not result.get("cache_status")}
    pending = [row for row in rows if row["ticker"] not in completed]
    history = charts.database(args.state_dir / "history.sqlite" if args.state_dir else None)
    if args.state_dir:
        history.execute("PRAGMA journal_mode=WAL")
        history.execute("PRAGMA busy_timeout=30000")
    mappings = {value["ticker"]: value["symbol"] for path in (args.state_dir / "mappings").glob("*.json") if (value := json.loads(path.read_text(encoding="utf-8"))).get("symbol")} if args.state_dir else {}
    if args.import_europe_cache or args.import_chart_cache:
        imported = 0
        for row in pending:
            symbol = information.symbols(row)[0]
            if not args.import_chart_cache and not symbol.startswith(("EURONEXT:", "XETR:", "SIX:", "LSE:")):
                continue
            path = next((candidate for count in [3700, 3200, 2800, 2500, 2000, 1500, 1000]
                         if (candidate := information.ROOT / "data/tmp_tradingview_chart/1D" / (hashlib.sha256(f"{symbol}:1D:{count}".encode()).hexdigest() + ".json")).exists()), None)
            if path is None:
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                if not information.fresh(payload.get("fetched_at")):
                    continue
                value = charts.parse_tradingview(payload, symbol)
                if len(value["prices"]) < 2:
                    continue
                value["ticker"] = row["ticker"]
                stored = history.execute("SELECT value FROM history WHERE ticker=?", (row["ticker"],)).fetchone()
                if stored and not value.get("first_trade_date"):
                    value["first_trade_date"] = json.loads(stored[0]).get("first_trade_date")
                value = request.bound(value)
                charts.save_candidate(history, value)
                result = {"ticker": row["ticker"], "order": row["order"], "queried_at": payload["fetched_at"], "error": None, "updated": True, "cache": str(path.relative_to(information.ROOT))}
                db.execute(f"INSERT OR REPLACE INTO {table} VALUES (?,?)", (row["ticker"], json.dumps(result)))
                completed.add(row["ticker"])
                imported += 1
            except (ValueError, KeyError, TypeError):
                continue
        history.commit(); db.commit()
        pending = [row for row in rows if row["ticker"] not in completed]
        print(f"Reused {imported} same-listing cached histories", flush=True)
    if args.retry_errors:
        retry = {ticker for ticker, raw in db.execute(f"SELECT ticker,value FROM {table}") if not json.loads(raw).get("updated")}
        retry.update(ticker for ticker, raw in history.execute("SELECT ticker,value FROM history") if len(json.loads(raw)["prices"]) < 2)
        completed = {row["ticker"] for row in rows if row["ticker"] not in retry}
        pending = [row for row in rows if row["ticker"] in retry]
    if args.refresh_tradingview:
        retry = {ticker for ticker, raw in history.execute("SELECT ticker,value FROM history") if "TradingView" in json.loads(raw).get("source", "")}
        completed = {row["ticker"] for row in rows if row["ticker"] not in retry}
        pending = [row for row in rows if row["ticker"] in retry]
    if args.extend_to_start:
        retry = {ticker for ticker, raw in history.execute("SELECT ticker,value FROM history") if needs_historical_extension(json.loads(raw), request)}
        completed = {row["ticker"] for row in rows if row["ticker"] not in retry}
        pending = [row for row in rows if row["ticker"] in retry]
    if args.exclude_market:
        pending = [row for row in pending if row["market"] != args.exclude_market]
    cursor = 0
    with ThreadPoolExecutor(max_workers=6) as pool:
        while cursor < len(pending):
            batch = []
            yahoo_batch = bool(charts.yahoo_symbol(pending[cursor]["ticker"])) and not args.refresh_tradingview
            while cursor < len(pending) and len(batch) < 20 and (bool(charts.yahoo_symbol(pending[cursor]["ticker"])) and not args.refresh_tradingview) == yahoo_batch:
                batch.append(pending[cursor]); cursor += 1
            values, errors = {}, {}
            if yahoo_batch:
                try:
                    now = datetime.now(timezone.utc)
                    years = (now.date() - date.fromisoformat(request.storage_start())).days / 365.25
                    requested_range = next((f"{size}y" for size in [2, 5, 10] if years <= size), "max")
                    params = {"symbols": ",".join(charts.yahoo_symbol(row["ticker"]) for row in batch), "range": requested_range, "interval": "1d"}
                    payload = information.fetch_json("https://query1.finance.yahoo.com/v7/finance/spark?" + urlencode(params))
                    returned = {item["symbol"].upper(): item for item in payload.get("spark", {}).get("result", [])}
                    for row in batch:
                        try:
                            result = returned[charts.yahoo_symbol(row["ticker"])]["response"][0]
                            value = charts.parse_yahoo({"chart": {"result": [result]}}, row["ticker"])
                            value = request.bound(value)
                            if args.extend_to_start and needs_historical_extension(value, request):
                                raise ValueError("Spark omitted the requested historical start; checking dated chart")
                            value.update(source="Yahoo Finance daily chart (spark)", requested_range=requested_range,
                                         requested_start=request.storage_start(), requested_end=request.end,
                                         fetched_at=datetime.now(timezone.utc).isoformat())
                            values[row["ticker"]] = value
                        except Exception as exc:
                            errors[row["ticker"]] = str(exc)
                except Exception as exc:
                    if getattr(exc, "code", None) in {403, 429}:
                        raise RuntimeError("Source access limited; saved stocks can be resumed later") from exc
                    errors = {row["ticker"]: str(exc) for row in batch}
            fallbacks = [row for row in batch if row["ticker"] not in values]
            futures = [pool.submit(fallback, row, mappings.get(row["ticker"]), request) for row in fallbacks]
            for row, future in zip(fallbacks, futures):
                try:
                    values[row["ticker"]] = future.result()
                    errors.pop(row["ticker"], None)
                except Exception as exc:
                    if getattr(exc, "code", None) in {403, 429}:
                        raise RuntimeError("Source access limited; saved stocks can be resumed later") from exc
                    errors[row["ticker"]] = f"{errors.get(row['ticker'], '')} TradingView: {exc}".strip()
            for row in batch:
                ticker = row["ticker"]
                if value := values.get(ticker):
                    old = history.execute("SELECT value FROM history WHERE ticker=?", (ticker,)).fetchone()
                    if old and not value.get("first_trade_date"):
                        value["first_trade_date"] = json.loads(old[0]).get("first_trade_date")
                    charts.save_candidate(history, value, historical_start=max(request.start, value.get("first_trade_date") or request.start) if args.extend_to_start else None); history.commit()
                    if value.get("first_trade_date"):
                        stored = json.loads(history.execute("SELECT value FROM history WHERE ticker=?", (ticker,)).fetchone()[0])
                        if not stored.get("first_trade_date"):
                            stored["first_trade_date"] = value["first_trade_date"]
                            history.execute("UPDATE history SET value=? WHERE ticker=?", (json.dumps(stored, ensure_ascii=False), ticker))
                            history.commit()
                result = {"ticker": ticker, "order": row["order"], "queried_at": datetime.now(timezone.utc).isoformat(), "error": errors.get(ticker), "updated": ticker in values}
                db.execute(f"INSERT OR REPLACE INTO {table} VALUES (?,?)", (ticker, json.dumps(result, ensure_ascii=False)))
                db.commit(); completed.add(ticker)
            charts.write_json(information.AUDIT / audit_file, {"requested_start": request.start, "requested_end": request.end,
                "price_reference_start": request.reference_start, "state_table": table,
                "total": len(rows), "checked": len(completed), "last": batch[-1],
                "resume": resume, "source_errors": db.execute(f"SELECT count(*) FROM {table} WHERE json_extract(value,'$.updated')=0").fetchone()[0]})
            print(f"Daily histories {len(completed)}/{len(rows)} {batch[-1]['ticker']} errors={len(errors)}", flush=True)
    information.checkpoint(db, rows, history, history_request=request, history_resume=resume,
                           audit_dir=None if request.scope == "2014" else information.AUDIT / "price-ranges" / request.scope)
    charts.export_packs(history)
    history.close(); db.close()


if __name__ == "__main__":
    main()
