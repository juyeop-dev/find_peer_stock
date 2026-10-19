"""Resume original daily price refreshes for the 2025-to-present information update."""
from concurrent.futures import ThreadPoolExecutor
import argparse
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import sys
from urllib.parse import urlencode

import stock_chart_history as charts
import stock_information as information


def tradingview(row):
    from quote_sources.tradingview_chart import fetch_chart
    candidates = information.symbols(row)
    if len(candidates) != 1:
        raise ValueError("Exact trading venue unavailable")
    symbol = candidates[0]
    days = (datetime.now(timezone.utc).date() - date(2024, 12, 20)).days
    count = min(5000, max(550, (days * 5 + 6) // 7 + 60))
    payload = fetch_chart(symbol, "1D", count, timeout=15)
    value = charts.parse_tradingview(payload, symbol)
    if len(value["prices"]) < 2:
        raise ValueError("Fewer than two valid original daily prices")
    value["ticker"] = row["ticker"]
    value["fetched_at"] = datetime.now(timezone.utc).isoformat()
    value["provider_date"] = value["prices"][-1][0]
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--retry-errors", action="store_true")
    parser.add_argument("--refresh-tradingview", action="store_true")
    args = parser.parse_args()
    sys.path.insert(0, str(information.ROOT / "data/tmp_info_update/deps"))
    rows = charts.roster()
    db = information.open_database()
    db.execute("CREATE TABLE IF NOT EXISTS history_updates(ticker TEXT PRIMARY KEY,value TEXT NOT NULL)")
    completed = {ticker for ticker, raw in db.execute("SELECT ticker,value FROM history_updates") if information.fresh(json.loads(raw).get("queried_at"), hours=20)}
    pending = [row for row in rows if row["ticker"] not in completed]
    history = charts.database()
    if args.retry_errors:
        retry = {ticker for ticker, raw in db.execute("SELECT ticker,value FROM history_updates") if not json.loads(raw).get("updated")}
        retry.update(ticker for ticker, raw in history.execute("SELECT ticker,value FROM history") if len(json.loads(raw)["prices"]) < 2)
        completed = {row["ticker"] for row in rows if row["ticker"] not in retry}
        pending = [row for row in rows if row["ticker"] in retry]
    if args.refresh_tradingview:
        retry = {ticker for ticker, raw in history.execute("SELECT ticker,value FROM history") if "TradingView" in json.loads(raw).get("source", "")}
        completed = {row["ticker"] for row in rows if row["ticker"] not in retry}
        pending = [row for row in rows if row["ticker"] in retry]
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
                    years = (now.date() - date(2024, 12, 20)).days / 365.25
                    requested_range = next((f"{size}y" for size in [2, 5, 10] if years <= size), "max")
                    params = {"symbols": ",".join(charts.yahoo_symbol(row["ticker"]) for row in batch), "range": requested_range, "interval": "1d"}
                    payload = information.fetch_json("https://query1.finance.yahoo.com/v7/finance/spark?" + urlencode(params))
                    returned = {item["symbol"].upper(): item for item in payload.get("spark", {}).get("result", [])}
                    for row in batch:
                        try:
                            result = returned[charts.yahoo_symbol(row["ticker"])]["response"][0]
                            value = charts.parse_yahoo({"chart": {"result": [result]}}, row["ticker"])
                            if len(value["prices"]) < 2:
                                raise ValueError("Fewer than two valid original daily prices")
                            if requested_range != "2y":
                                # Bound storage while retaining both the requested 2025 start and two years.
                                cutoff = min("2024-12-20", (now.date() - timedelta(days=732)).isoformat())
                                value["prices"] = [point for point in value["prices"] if point[0] >= cutoff]
                            value.update(source="Yahoo Finance daily chart (spark)", requested_range=requested_range, fetched_at=datetime.now(timezone.utc).isoformat())
                            values[row["ticker"]] = value
                        except Exception as exc:
                            errors[row["ticker"]] = str(exc)
                except Exception as exc:
                    if getattr(exc, "code", None) in {403, 429}:
                        raise RuntimeError("Source access limited; saved stocks can be resumed later") from exc
                    errors = {row["ticker"]: str(exc) for row in batch}
            fallbacks = [row for row in batch if row["ticker"] not in values]
            futures = [pool.submit(tradingview, row) for row in fallbacks]
            for row, future in zip(fallbacks, futures):
                try:
                    values[row["ticker"]] = future.result()
                    errors.pop(row["ticker"], None)
                except Exception as exc:
                    errors[row["ticker"]] = f"{errors.get(row['ticker'], '')} TradingView: {exc}".strip()
            for row in batch:
                ticker = row["ticker"]
                if value := values.get(ticker):
                    old = history.execute("SELECT value FROM history WHERE ticker=?", (ticker,)).fetchone()
                    if old and not value.get("first_trade_date"):
                        value["first_trade_date"] = json.loads(old[0]).get("first_trade_date")
                    charts.save_candidate(history, value); history.commit()
                result = {"ticker": ticker, "order": row["order"], "queried_at": datetime.now(timezone.utc).isoformat(), "error": errors.get(ticker), "updated": ticker in values}
                db.execute("INSERT OR REPLACE INTO history_updates VALUES (?,?)", (ticker, json.dumps(result, ensure_ascii=False)))
                db.commit(); completed.add(ticker)
            charts.write_json(information.AUDIT / "history-progress.json", {"requested_start": information.START, "total": len(rows), "checked": len(completed), "last": batch[-1],
                "resume": "python scripts/refresh_stock_information_history.py", "source_errors": db.execute("SELECT count(*) FROM history_updates WHERE json_extract(value,'$.updated')=0").fetchone()[0]})
            print(f"Daily histories {len(completed)}/{len(rows)} {batch[-1]['ticker']} errors={len(errors)}", flush=True)
    information.checkpoint(db, rows, history)
    charts.export_packs(history)
    history.close(); db.close()


if __name__ == "__main__":
    main()
