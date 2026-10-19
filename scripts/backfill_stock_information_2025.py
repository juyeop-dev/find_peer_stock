"""Recover 2025 quarters omitted by the financial provider's rolling result limit."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from urllib.parse import quote, urlencode

import stock_information as info
import stock_chart_history as charts


def fetch(row):
    symbol = charts.yahoo_symbol(row["ticker"])
    if not symbol:
        return [], "같은 상장 종목의 Yahoo 코드가 없어 TradingView 제공 회계기간을 유지합니다."
    types = ["quarterly" + field for field in info.METRICS.values()]
    params = {"type": ",".join(types), "period1": 1735689600, "period2": 1767225600}
    payload = info.fetch_json(f"https://query1.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/{quote(symbol, safe='')}?{urlencode(params)}")
    return info.parse_yahoo_financials(payload, symbol, "2025-12-31"), None


def main():
    db = info.open_database()
    db.execute("CREATE TABLE IF NOT EXISTS financial_2025_updates(ticker TEXT PRIMARY KEY,value TEXT NOT NULL)")
    completed = {ticker for ticker, in db.execute("SELECT ticker FROM financial_2025_updates")}
    for ticker, raw in db.execute("SELECT ticker,value FROM information"):
        if info.fresh(json.loads(raw).get("historical_financials_fetched_at"), hours=24 * 30): completed.add(ticker)
    rows = charts.roster()
    pending = [row for row in rows if row["ticker"] not in completed]
    with ThreadPoolExecutor(max_workers=8) as pool:
        for start in range(0, len(pending), 40):
            batch = pending[start:start + 40]
            futures = [pool.submit(fetch, row) for row in batch]
            for row, future in zip(batch, futures):
                error = None
                try:
                    financials, error = future.result()
                except Exception as exc:
                    if getattr(exc, "code", None) in {403, 429}:
                        raise RuntimeError("Source access limited; saved stocks can be resumed later") from exc
                    financials, error = [], f"{type(exc).__name__}: {exc}"
                # The main collector may be running. Merge under a brief write transaction.
                db.execute("BEGIN IMMEDIATE")
                stored = db.execute("SELECT value FROM information WHERE ticker=?", (row["ticker"],)).fetchone()
                if stored:
                    value = json.loads(stored[0])
                    keys = {(item["type"], item["period_end"]) for item in value["financials"]}
                    added = [item for item in financials if (item["type"], item["period_end"]) not in keys]
                    value["financials"] = sorted(value["financials"] + added, key=lambda item: (item["period_end"], item["type"]))
                    value["historical_financials_fetched_at"] = datetime.now(timezone.utc).isoformat()
                    dates = sorted(item["period_end"] for item in value["financials"])
                    value.setdefault("financial_coverage", {})["first_period"] = dates[0] if dates else None
                    value["financial_coverage"]["latest_period"] = dates[-1] if dates else None
                    if error:
                        value["historical_financials_warning"] = error
                    db.execute("INSERT OR REPLACE INTO information VALUES (?,?)", (row["ticker"], json.dumps(value, ensure_ascii=False, separators=(",", ":"))))
                else:
                    db.rollback()
                    raise RuntimeError(f"Main information collector has not reached {row['ticker']}; resume later")
                result = {"ticker": row["ticker"], "order": row["order"], "periods_found": len(financials), "error": error, "queried_at": datetime.now(timezone.utc).isoformat()}
                db.execute("INSERT OR REPLACE INTO financial_2025_updates VALUES (?,?)", (row["ticker"], json.dumps(result, ensure_ascii=False)))
                db.commit(); completed.add(row["ticker"])
            info.charts.write_json(info.AUDIT / "financial-2025-progress.json", {"total": len(rows), "checked": len(completed), "last": batch[-1], "requested_start": info.START,
                "resume": "python scripts/backfill_stock_information_2025.py", "exceptions": db.execute("SELECT count(*) FROM financial_2025_updates WHERE json_extract(value,'$.error') IS NOT NULL").fetchone()[0]})
            print(f"2025 financials {len(completed)}/{len(rows)} {batch[-1]['ticker']}", flush=True)
    db.close()


if __name__ == "__main__":
    main()
