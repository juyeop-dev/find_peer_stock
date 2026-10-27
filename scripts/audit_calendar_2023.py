"""Validate complete 2023 calendars and dated domestic reference series."""
from datetime import date, datetime, timedelta, timezone
import gzip
import json

from stock_chart_history import ROOT, write_json


def main():
    config = json.loads((ROOT / "data/market-closures/2023.json").read_bytes())
    weekdays = {(date(2023, 1, 1) + timedelta(days=i)).isoformat() for i in range(365)
                if (date(2023, 1, 1) + timedelta(days=i)).weekday() < 5}
    result = {"year": 2023, "validated_at": datetime.now(timezone.utc).isoformat(), "markets": {}}
    for market in config["markets"]:
        key = market["market"]
        expected = weekdays - set(market["dates"])
        counts = {}
        for kind in ["new-highs", "turnover"]:
            reports = [json.loads(path.read_bytes()) for path in (ROOT / "data" / kind / "reports" / key).rglob("2023-*.json")]
            dates = [report["date"] for report in reports]
            assert len(dates) == len(set(dates)), (kind, key, "Duplicate session")
            assert set(dates) == expected, (kind, key, sorted(expected - set(dates)), sorted(set(dates) - expected))
            for report in reports:
                assert report["market"] == key and report["schema_version"] == 1
                entries = report["entries"]
                assert len({row["ticker"] for row in entries}) == len(entries)
                if kind == "turnover":
                    assert len(entries) == 30 and [row["rank"] for row in entries] == list(range(1, 31))
                    assert all(a["turnover"] >= b["turnover"] > 0 for a, b in zip(entries, entries[1:]))
                    if key == "korea":
                        assert report["source_metadata"]["ranking"].startswith("KRX Amount")
                        assert all(row["market_cap_date"] == report["date"] and row["currency"] == "KRW" for row in entries)
                if key == "europe":
                    assert report["source_metadata"]["coverage_status"] == "partial"
                    assert "부분 복원" in report["summary"]
            counts[kind] = len(reports)
        result["markets"][key] = counts
    korean_days = weekdays - set(next(m for m in config["markets"] if m["market"] == "korea")["dates"])
    sector_paths = list((ROOT / "data/sectors/daily").glob("2023-*.json.gz"))
    assert {path.name[:10] for path in sector_paths} == korean_days
    for path in sector_paths:
        snapshot = json.loads(gzip.decompress(path.read_bytes()))
        assert snapshot["historical_metrics"]["matched"] > 1500
        assert snapshot["reconstruction"]["classification_date"] > snapshot["date"]
        assert all(row.get("market_cap_date") == snapshot["date"] for row in snapshot["stocks"] if row.get("market_cap") is not None)
    investors = json.loads((ROOT / "data/investors/index.json").read_bytes())
    assert {day["date"] for day in investors["history"] if day["date"].startswith("2023-")} == korean_days
    credit = json.loads((ROOT / "data/credit/index.json").read_bytes())
    result.update(sector_days=len(sector_paths), investor_days=len(korean_days),
                  credit_reporting_days=sum(row["date"].startswith("2023-") for row in credit["history"]))
    write_json(ROOT / "data/information-audit/2023/calendar-coverage.json", result)
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
