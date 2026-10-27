"""Recheck omitted archive dates against exact, dated original Yahoo listings."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path
import subprocess
from urllib.parse import quote, urlencode

import stock_chart_history as charts
import stock_information as info


def fetch_original(ticker, symbol):
    now = datetime.now(timezone.utc)
    params = {"period1": int(datetime(2022, 12, 20, tzinfo=timezone.utc).timestamp()),
              "period2": int(now.timestamp()) + 60, "interval": "1d"}
    payload = info.fetch_json(f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol, safe='')}?{urlencode(params)}")
    value = charts.parse_yahoo(payload, symbol)
    value.update(ticker=ticker, source_symbol=symbol, fetched_at=now.isoformat(), requested_range="dated", requested_start="2022-12-20")
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--archive-only", action="store_true", help="Preserve revised/omitted prior observations as separate snapshots without mixing adjustment conventions.")
    args = parser.parse_args()
    state = info.ROOT / "data/tmp_2023_history"
    charts.DATABASE = state / "history.sqlite"
    db = charts.database()
    mappings = {v["ticker"]: v["symbol"] for path in (state / "mappings").glob("*.json")
                if (v := json.loads(path.read_bytes())).get("symbol")}
    pending = []
    originals = {}
    for shard in "0123456789abcdef":
        raw = subprocess.check_output(["git", "cat-file", "blob", f"{args.baseline}:data/stock-history/{shard}.json.gz"], cwd=info.ROOT)
        for ticker, old in json.loads(gzip.decompress(raw)).items():
            stored = db.execute("SELECT value FROM history WHERE ticker=?", (ticker,)).fetchone()
            if not stored:
                continue
            current = json.loads(stored[0])
            dates = {p[0] for p in current["prices"]}
            missing = [p[0] for p in old["prices"] if p[0] not in dates]
            if missing:
                symbol = charts.yahoo_symbol(ticker) or old.get("source_symbol") or mappings.get(ticker)
                pending.append((ticker, symbol, missing))
                originals[ticker] = old
    results = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(fetch_original, ticker, symbol) if symbol and not args.archive_only else None for ticker, symbol, _ in pending]
        for (ticker, symbol, missing), future in zip(pending, futures):
            result = {"ticker": ticker, "symbol": symbol, "previously_omitted_dates": missing}
            try:
                if args.archive_only:
                    pass
                elif not future:
                    raise ValueError("No verified original Yahoo listing")
                else:
                    value = future.result()
                    charts.save_candidate(db, value)
                    db.commit()
            except Exception as exc:
                if getattr(exc, "code", None) in {403, 429}:
                    raise
                result["error"] = str(exc)
            stored = json.loads(db.execute("SELECT value FROM history WHERE ticker=?", (ticker,)).fetchone()[0])
            dates = {p[0] for p in stored["prices"]}
            result["remaining_missing_dates"] = [day for day in missing if day not in dates]
            if args.archive_only and result["remaining_missing_dates"]:
                snapshots = [snapshot for snapshot in stored.get("prior_snapshots", []) if snapshot.get("preserved_from_git") != args.baseline]
                snapshots.append({**originals[ticker], "preserved_from_git": args.baseline,
                    "preservation_reason": "The original provider revised or omitted these dates in its latest response. Preserve the prior source and adjustment convention separately.",
                    "omitted_dates": result["remaining_missing_dates"]})
                stored["prior_snapshots"] = snapshots
                db.execute("UPDATE history SET value=? WHERE ticker=?", (json.dumps(stored, ensure_ascii=False, separators=(",", ":")), ticker))
                db.commit()
                result["prior_snapshot_preserved"] = True
            results.append(result)
            if len(results) % 50 == 0:
                print(f"Dated original histories {len(results)}/{len(pending)}", flush=True)
    name = "history-prior-snapshots.json" if args.archive_only else "history-preservation-rechecks.json"
    charts.write_json(info.AUDIT / "2023" / name, {"baseline": args.baseline, "results": results})
    charts.export_packs(db)
    db.close()
    if args.archive_only:
        print(f"Preserved {sum(bool(r.get('prior_snapshot_preserved')) for r in results)} original snapshots without mixing price conventions", flush=True)
    else:
        print(f"Rechecked {len(results)}; date sets requiring separate preservation: {sum(bool(r['remaining_missing_dates']) for r in results)}", flush=True)


if __name__ == "__main__":
    main()
