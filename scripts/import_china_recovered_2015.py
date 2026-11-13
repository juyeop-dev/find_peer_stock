"""Use coherent verified China histories; preserve or exclude bad Yahoo fills."""
from datetime import datetime, timezone
import argparse
import hashlib
import json

from backfill_yahoo_calendars import archive_ticker
from extend_stock_history_2023 import cached_yahoo_path
from import_recovered_histories_2019 import retain_curve
import stock_chart_history as charts

DAY = "2015-02-25"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-export", action="store_true")
    args = parser.parse_args()
    universe = json.loads((charts.ROOT / "data/tmp_2015/china-gap-universe.json").read_bytes())
    proof = json.loads((charts.ROOT / "data/information-audit/2015/china-gap-recovery.json").read_bytes())
    charts.DATABASE = charts.ROOT / "data/tmp_2015_history/history.sqlite"
    db = charts.database()
    imported, excluded = [], []
    for row in universe["rows"]:
        ticker, symbol = archive_ticker(row), row["symbol"]
        stored = db.execute("SELECT value FROM history WHERE ticker=?", (ticker,)).fetchone()
        previous = json.loads(stored[0]) if stored else None
        recovery = proof["histories"].get(symbol)
        path = charts.ROOT / "data/tmp_tradingview_chart/1D" / (hashlib.sha256(f"{symbol}:1D:3200".encode()).hexdigest()+".json")
        if recovery and path.exists():
            payload = json.loads(path.read_bytes())
            assert hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest() == recovery["sha256"]
            fresh = charts.parse_tradingview(payload, symbol)
            if any(point[0] == DAY for point in fresh["prices"]):
                fresh.update(ticker=ticker, source_symbol=symbol, first_trade_date=(previous or {}).get("first_trade_date"),
                    prices=[point for point in fresh["prices"] if point[0] >= "2014-12-20"],
                    historical_2015_china_recovery={"date": DAY, "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
                merged, alternate = retain_curve(previous, fresh) if previous else (fresh, False)
                db.execute("INSERT OR REPLACE INTO history VALUES (?,?)", (ticker,json.dumps(merged,ensure_ascii=False,separators=(",",":"),allow_nan=False)))
                imported.append({"ticker":ticker,"alternate":alternate})
                if not alternate:
                    continue
                previous = merged
        if not previous or "Yahoo" not in previous.get("source", ""):
            continue
        original = cached_yahoo_path(ticker, 2015)
        if not original.exists():
            continue
        raw = json.loads(original.read_bytes())["chart"]["result"][0]
        from zoneinfo import ZoneInfo
        volumes = raw["indicators"]["quote"][0].get("volume", [])
        bad = any(datetime.fromtimestamp(stamp,ZoneInfo(raw["meta"]["exchangeTimezoneName"])).date().isoformat()==DAY
                  and i<len(volumes) and volumes[i]==0 for i,stamp in enumerate(raw.get("timestamp",[])))
        if not bad or not any(point[0] == DAY for point in previous["prices"]):
            continue
        snapshot = {key:value for key,value in previous.items() if key!="prior_snapshots"}
        snapshot.update(complete_history=False,preservation_reason="Unverified zero-volume provider fill on 2015-02-25 retained only as provenance")
        value = {**previous,"prices":[point for point in previous["prices"] if point[0]!=DAY],
            "prior_snapshots":[*previous.get("prior_snapshots",[]),snapshot],"excluded_2015_unverified_dates":[DAY]}
        db.execute("UPDATE history SET value=? WHERE ticker=?",(json.dumps(value,ensure_ascii=False,separators=(",",":")),ticker))
        excluded.append(ticker)
    db.commit()
    if not args.no_export:
        charts.export_packs(db)
    db.close()
    result={"checked_at":datetime.now(timezone.utc).isoformat(),"date":DAY,"imported":imported,"unverified_excluded":excluded}
    charts.write_json(charts.ROOT/"data/information-audit/2015/china-price-recovery.json",result)
    print(f"Imported {len(imported)} coherent China curves; excluded {len(excluded)} unverified fills",flush=True)


if __name__ == "__main__":
    main()
