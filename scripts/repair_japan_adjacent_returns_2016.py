"""Repair July 12 returns whose prior Yahoo close was an unverified fill."""
from datetime import datetime
import hashlib
import json
from zoneinfo import ZoneInfo

from archive_paths import monthly_report_path
from stock_chart_history import ROOT, write_json


def main():
    proof = json.loads((ROOT / "data/information-audit/2016/japan-gap-recovery.json").read_bytes())
    changes = []
    backup = ROOT / "data/tmp_2016/japan-replaced-reports"
    for kind in ["new-highs", "turnover"]:
        path = ROOT / "data/new-highs/reports/japan/2016-07-12.json" if kind == "new-highs" else monthly_report_path(ROOT / "data/turnover/reports", "japan", "2016-07-12")
        old = path.read_bytes()
        value = json.loads(old)
        target = backup / f"{kind}-2016-07-12.json"
        if not target.exists():
            target.write_bytes(old)
        for row in value["entries"]:
            symbol = row.get("source_symbol") or "TSE:" + row["ticker"].split(".")[0]
            record = proof["histories"].get(symbol)
            chart = ROOT / "data/tmp_tradingview_chart/1D" / (hashlib.sha256(f"{symbol}:1D:3200".encode()).hexdigest()+".json")
            observations = {}
            if record and chart.exists():
                payload = json.loads(chart.read_bytes())
                assert hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest() == record["sha256"]
                observations = {datetime.fromtimestamp(bar["timestamp"],ZoneInfo(payload["info"]["timezone"])).date().isoformat():bar
                    for bar in payload["bars"]}
            a,b = observations.get("2016-07-11"),observations.get("2016-07-12")
            before = row.get("change_pct")
            row["change_pct"] = (b["close"]/a["close"]-1)*100 if a and b and a["close"]>0 and b["close"]>0 else None
            row["change_verification"] = {"source":"Same-listing TradingView actual closes", "date":"2016-07-12", "previous_date":"2016-07-11",
                "source_symbol":symbol, "source_sha256":record["sha256"] if record else None,
                "reason":"Yahoo prior-day zero-volume fill cannot establish the daily change"}
            changes.append({"kind":kind,"ticker":row["ticker"],"before":before,"after":row["change_pct"]})
        value["source_metadata"]["daily_change_recovery"] = "2016-07-12 returns use verified same-listing July 11 and 12 closes; missing observations stay null"
        write_json(path,value)
    write_json(ROOT / "data/information-audit/2016/japan-adjacent-returns.json",{"changes":changes})
    print(f"Rechecked {len(changes)} Japan July 12 daily returns",flush=True)


if __name__ == "__main__":
    main()
