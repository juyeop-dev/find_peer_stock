"""Compare all published 2016 reports and domestic references to durable sources."""
import argparse
from datetime import date, timedelta
import gzip
import json
from pathlib import Path
from urllib.parse import quote

from stock_chart_history import ROOT, write_json


def load(path):
    if not path.exists() and not path.name.endswith(".gz"):
        path = path.with_name(path.name + ".gz")
    raw = path.read_bytes()
    value = json.loads(gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw)
    if isinstance(value, dict) and value.get("encoding") == "sector-columns-v1":
        fields = value.pop("stock_fields")
        rows = value.pop("stock_rows")
        value.pop("encoding")
        value["stocks"] = [dict(zip(fields[row[0]], row[1:], strict=True)) for row in rows]
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path)
    args = parser.parse_args()
    public = (args.artifact.resolve() / "data") if args.artifact else ROOT / "frontend/public/data"
    counts = {}
    config = load(ROOT / "data/market-closures/2016.json")
    weekdays = {(date(2016, 1, 1) + timedelta(days=i)).isoformat() for i in range(366)
                if (date(2016, 1, 1) + timedelta(days=i)).weekday() < 5}
    expected = sum(len((weekdays | set(row.get("additional_open_dates", {}))) - set(row["dates"])) for row in config["markets"])
    for kind in ["new-highs", "turnover"]:
        count = 0
        for path in (ROOT / "data/generated" / kind).rglob("2016-*.json"):
            relative = path.relative_to(ROOT / "data/generated")
            target = public / relative.with_suffix(".json.gz")
            assert load(target) == load(path), relative
            count += 1
        assert count == expected, (kind, count, expected)
        counts[kind] = count
    for kind in ["investors", "credit"]:
        source = load(ROOT / f"data/{kind}/index.json")
        assert load(public / f"{kind}/index.json") == source, kind
        counts[kind] = sum(row["date"].startswith("2016-") for row in source["history"])
    source = load(ROOT / "data/semiconductor/index.json")
    by_ticker = {row["ticker"]: row for row in load(public / "semiconductor/index.json")["stocks"]}
    for row in source["stocks"]:
        assert by_ticker[row["ticker"]]["history"] == row["history"], row["ticker"]
    counts["semiconductor_histories"] = len(by_ticker)
    histories = information = 0
    for path in (ROOT / "data/stock-history").glob("*.gz"):
        for ticker, value in load(path).items():
            filename = quote(ticker, safe="").replace("%", "~") + ".json.gz"
            published = load(public / "stock-history" / filename)
            assert published["ticker"] == ticker and published["currency"] == value["currency"], ticker
            assert published["prices"] == value["prices"], ticker
            assert all(not row.get("rejected_daily_granularity") for row in published.get("prior_snapshots", [])), ticker
            histories += 1
    for path in (ROOT / "data/stock-information").glob("*.gz"):
        for ticker, value in load(path).items():
            filename = quote(ticker, safe="").replace("%", "~") + ".json.gz"
            published = load(public / "stock-information" / filename)
            assert published["ticker"] == ticker, ticker
            for field in ["financials", "quote", "metrics", "historical_2016_coverage"]:
                assert published.get(field) == value.get(field), (ticker, field)
            information += 1
    counts.update(continuous_stock_histories=histories, information_snapshots=information)
    rebound_paths = list((ROOT / "data/rebounds/reports/korea").glob("2016_*/*.json"))
    for path in rebound_paths:
        relative = path.relative_to(ROOT / "data/rebounds/reports")
        assert load(public / "rebounds" / relative) == load(path), relative
    counts["rebound_sessions"] = len(rebound_paths)
    assert counts["rebound_sessions"] == 246
    assert load(public / "chart-replay/markets.json") == load(ROOT / "data/chart-replay/markets.json")
    if args.artifact:
        artifact = args.artifact.resolve()
        assert artifact.is_relative_to(ROOT), artifact
        files = [path for path in artifact.rglob("*") if path.is_file()]
        assert (artifact / "index.html").exists()
        counts.update(artifact_files=len(files), artifact_bytes=sum(path.stat().st_size for path in files))
        assert counts["artifact_bytes"] < 1024**3, counts
    write_json(ROOT / "data/information-audit/2016/publication.json", counts)
    print(json.dumps(counts))


if __name__ == "__main__":
    main()
