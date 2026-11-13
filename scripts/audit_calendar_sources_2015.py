"""Detect mass zero-volume/provider holiday placeholders in retained daily originals."""
from collections import defaultdict
from datetime import date, datetime, timezone
import json
import subprocess
import sys
from zoneinfo import ZoneInfo

import stock_chart_history as charts
from backfill_yahoo_calendars import requested_dates
from extend_stock_history_2023 import cached_yahoo_path


def main():
    results = {}
    roster = charts.roster()
    for market in ["us", "japan", "china", "taiwan"]:
        sessions = {str(day): {"observed": 0, "zero_volume": 0} for day in requested_dates(date(2015, 1, 1), date(2015, 12, 31), market)}
        checked = 0
        for row in roster:
            if row["market"] != market:
                continue
            symbol = charts.yahoo_symbol(row["ticker"])
            if not symbol:
                continue
            path = cached_yahoo_path(symbol, 2015)
            if not path.exists():
                continue
            payload = json.loads(path.read_bytes())
            try:
                original = charts.parse_yahoo(payload, symbol)
            except (ValueError, KeyError, TypeError):
                continue
            if len(original["prices"]) < 2:
                continue
            result = payload["chart"]["result"][0]
            zone = ZoneInfo(result["meta"]["exchangeTimezoneName"])
            quotes = result["indicators"]["quote"][0]
            checked += 1
            for index, stamp in enumerate(result.get("timestamp", [])):
                day = datetime.fromtimestamp(stamp, zone).date().isoformat()
                close = quotes.get("close", [])[index]
                if day not in sessions or close is None or close <= 0:
                    continue
                sessions[day]["observed"] += 1
                volumes = quotes.get("volume", [])
                if index < len(volumes) and volumes[index] == 0:
                    sessions[day]["zero_volume"] += 1
        assert checked > 500, (market, "Not enough retained daily originals", checked)
        suspect = {day: counts for day, counts in sessions.items() if counts["observed"] < 100 or counts["zero_volume"] > counts["observed"] * .5}
        results[market] = {"checked_listing_originals": checked, "sessions": sessions, "suspect": suspect}
    repaired = {}
    unresolved = {}
    for market, value in results.items():
        unresolved[market] = dict(value["suspect"])
        quality = charts.ROOT / f"data/information-audit/2015/{market}-quality.json"
        if not quality.exists():
            continue
        # Recheck the actual repaired reports/curves and their source hashes;
        # retaining an old success file is insufficient to waive a source error.
        subprocess.run([sys.executable, str(charts.ROOT / f"scripts/audit_{market}_quality_2015.py")], check=True)
        proof = json.loads(quality.read_bytes())
        if proof["date"] in unresolved[market] and proof["verified_listings"] > 1500 and proof["coherent_curves"] > 1000 and proof["turnover_top30_verified"] and proof["adjacent_returns_verified"]:
            repaired[market] = {"date": proof["date"], "evidence": quality.relative_to(charts.ROOT).as_posix()}
            unresolved[market].pop(proof["date"])
    charts.write_json(charts.ROOT / "data/information-audit/2015/calendar-source-quality.json", {
        "checked_at": datetime.now(timezone.utc).isoformat(), "markets": results,
        "independently_repaired": repaired, "unresolved": unresolved,
        "scope": "Retained exact-listing Yahoo daily originals, not a claim to the complete historical listed universe"})
    assert not any(unresolved.values()), unresolved
    print({market: {"originals": value["checked_listing_originals"], "sessions": len(value["sessions"]), "raw_suspect": len(value["suspect"]), "unresolved": len(unresolved[market])} for market, value in results.items()})


if __name__ == "__main__":
    main()
