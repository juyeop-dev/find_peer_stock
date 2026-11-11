"""Compare all published 2017 reports and domestic references to durable sources."""
import argparse
from datetime import date, timedelta
import gzip
import json
from pathlib import Path

from stock_chart_history import ROOT, write_json


def load(path):
    raw = path.read_bytes()
    return json.loads(gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path)
    args = parser.parse_args()
    public = ROOT / "frontend/public/data"
    counts = {}
    config = load(ROOT / "data/market-closures/2017.json")
    weekdays = {(date(2017, 1, 1) + timedelta(days=i)).isoformat() for i in range(365)
                if (date(2017, 1, 1) + timedelta(days=i)).weekday() < 5}
    expected = sum(len((weekdays | set(row.get("additional_open_dates", {}))) - set(row["dates"])) for row in config["markets"])
    for kind in ["new-highs", "turnover"]:
        count = 0
        for path in (ROOT / "data/generated" / kind).rglob("2017-*.json"):
            relative = path.relative_to(ROOT / "data/generated")
            target = public / relative.with_suffix(".json.gz")
            assert load(target) == load(path), relative
            count += 1
        assert count == expected, (kind, count, expected)
        counts[kind] = count
    for kind in ["investors", "credit"]:
        source = load(ROOT / f"data/{kind}/index.json")
        assert load(public / f"{kind}/index.json") == source, kind
        counts[kind] = sum(row["date"].startswith("2017-") for row in source["history"])
    source = load(ROOT / "data/semiconductor/index.json")
    by_ticker = {row["ticker"]: row for row in load(public / "semiconductor/index.json")["stocks"]}
    for row in source["stocks"]:
        assert by_ticker[row["ticker"]]["history"] == row["history"], row["ticker"]
    counts["semiconductor_histories"] = len(by_ticker)
    rebound_paths = list((ROOT / "data/rebounds/reports/korea").glob("2017_*/*.json"))
    for path in rebound_paths:
        relative = path.relative_to(ROOT / "data/rebounds/reports")
        assert load(public / "rebounds" / relative) == load(path), relative
    counts["rebound_sessions"] = len(rebound_paths)
    assert counts["rebound_sessions"] == 243
    assert load(public / "chart-replay/markets.json") == load(ROOT / "data/chart-replay/markets.json")
    if args.artifact:
        artifact = args.artifact.resolve()
        assert artifact.is_relative_to(ROOT), artifact
        files = [path for path in artifact.rglob("*") if path.is_file()]
        assert (artifact / "index.html").exists()
        counts.update(artifact_files=len(files), artifact_bytes=sum(path.stat().st_size for path in files))
        assert counts["artifact_bytes"] < 1024**3, counts
    write_json(ROOT / "data/information-audit/2017/publication.json", counts)
    print(json.dumps(counts))


if __name__ == "__main__":
    main()
