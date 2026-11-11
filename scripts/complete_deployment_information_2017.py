"""Check newly added production-calendar listings without replacing saved rows."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import gzip
import hashlib
import json

import stock_chart_history as charts
import stock_information as info
import backfill_stock_information_2017 as year
import backfill_stock_information_2024_h2 as recovery


def main():
    year.configure()
    rows = charts.roster()
    db = info.open_database(info.ROOT / "data/tmp_2017/deployment-information")
    existing = {ticker for ticker, in db.execute("SELECT ticker FROM information")}
    missing = [row for row in rows if row["ticker"] not in existing]
    info.scan(db, missing, datetime.now(timezone.utc).date().isoformat())
    scanners = {ticker: json.loads(raw) for ticker, raw in db.execute("SELECT ticker,value FROM scanner")}
    results, histories = [], {}

    def fetch(row):
        now = datetime.now(timezone.utc).isoformat()
        value = info.collect_one(row, scanners[row["ticker"]], now[:10])
        value = recovery.merge(value, [], now)
        try:
            history = charts.fetch_live_history(row)
            history.update(requested_start="2016-12-20", requested_range="dated")
            error = None
        except Exception as error_value:
            if getattr(error_value, "code", None) in {403, 429}:
                raise
            history, error = None, f"{type(error_value).__name__}: {error_value}"
        return row, value, history, error

    with ThreadPoolExecutor(max_workers=4) as pool:
        for row, value, history, error in pool.map(fetch, missing):
            db.execute("INSERT INTO information VALUES (?,?)", (row["ticker"], json.dumps(value, ensure_ascii=False)))
            db.commit()
            if history:
                histories[row["ticker"]] = history
            results.append({"ticker": row["ticker"], "quote": bool(value.get("quote")), "history": bool(history), "error": error})
            print(f"New production listing {row['ticker']}: quote={bool(value.get('quote'))}, history={bool(history)}", flush=True)
    if missing:
        info.export(db)
        for shard in "0123456789abcdef":
            updates = {key: value for key, value in histories.items() if hashlib.sha256(key.encode()).hexdigest()[0] == shard}
            if not updates:
                continue
            path = charts.PACKS / f"{shard}.json.gz"
            old = json.loads(gzip.decompress(path.read_bytes()))
            for ticker, value in updates.items():
                if ticker not in old:
                    old[ticker] = value
            raw = json.dumps(old, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
            path.write_bytes(gzip.compress(raw, compresslevel=6, mtime=0))
    db.close()
    charts.write_json(info.ROOT / "data/information-audit/2017/new-production-listings.json", {
        "total": len(rows), "added": len(missing), "listings": results, "checked_at": datetime.now(timezone.utc).isoformat()})
    print(f"Production universe: {len(rows)} listings, {len(missing)} new information checks", flush=True)


if __name__ == "__main__":
    main()
