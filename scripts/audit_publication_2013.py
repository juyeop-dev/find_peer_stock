"""Validate 2013 market sessions and financial periods against local publication."""
import argparse
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
from urllib.parse import quote

from archive_paths import monthly_report_path
from publication_readers import load, load_published_sector_day
from stock_chart_history import ROOT, write_json


def audit(public):
    source = ROOT / "data"
    calendar = load(source / "market-closures/2013.json")
    weekdays = {str(day) for offset in range(365)
                if (day := date(2013, 1, 1) + timedelta(days=offset)).weekday() < 5}
    sessions = {row["market"]: (weekdays | row.get("additional_open_dates", {}).keys()) - row["dates"].keys()
                for row in calendar["markets"]}
    result = {"schema_version": 1, "year": 2013, "checked_at": datetime.now(timezone.utc).isoformat()}
    input_hashes = {}
    for kind in ("new-highs", "turnover"):
        index = load(public / kind / "index.json")["reports"]
        counts = {}
        for market, days in sessions.items():
            indexed = {row["date"] for row in index if row["market"] == market and row["date"].startswith("2013-")}
            assert indexed == days, (kind, market, sorted(indexed ^ days))
            counts[market] = len(days)
            for day in sorted(days):
                if kind == "new-highs":
                    canonical = source / kind / "reports" / market / f"{day}.json"
                    exposed = public / kind / market / f"{day}.json"
                    fields = ("ticker", "session_close", "change_pct", "currency", "high_type")
                else:
                    canonical = monthly_report_path(source / kind / "reports", market, day)
                    exposed = monthly_report_path(public / kind, market, day)
                    fields = ("ticker", "price", "turnover", "change_pct", "currency")
                original, published = load(canonical), load(exposed)
                assert original["date"] == published["date"] == day and published["market"] == market
                for before, after in zip(original["entries"], published["entries"], strict=True):
                    assert all(before.get(key) == after.get(key) for key in fields), (kind, market, day, before["ticker"])
                input_hashes[canonical.relative_to(source).as_posix()] = sha256(canonical.read_bytes()).hexdigest()
        result[kind] = {"total_sessions": sum(counts.values()), "markets": counts}

    for day in sorted(sessions["korea"]):
        original = load(source / "sectors/daily" / f"{day}.json.gz")
        sector = load_published_sector_day(public / "sectors", day)
        assert original["date"] == sector["date"] == day
        for before, after in zip(original["stocks"], sector["stocks"], strict=True):
            assert all(before.get(key) == after.get(key) for key in ("ticker", "price", "market_cap", "turnover", "market_cap_date")), day
        assert load(monthly_report_path(source / "rebounds/reports", "korea", day)) == load(monthly_report_path(public / "rebounds", "korea", day)), day

    investor = load(public / "investors/index.json")["history"]
    assert investor == load(source / "investors/index.json")["history"]
    observed = [row for row in investor if row["date"].startswith("2013-")]
    assert {row["date"] for row in observed} == sessions["korea"] and len(observed) == len(sessions["korea"])
    for row in observed:
        assert len(row["markets"]) == 2 and {market["market"] for market in row["markets"]} == {"KOSPI", "KOSDAQ"}
        assert all(market["date"] == market["index"]["date"] == row["date"] and len(market["investors"]) == 4 for market in row["markets"])
    result.update(sectors=len(observed), rebounds=len(observed), investors=len(observed))

    credit = load(public / "credit/index.json")["history"]
    assert credit == load(source / "credit/index.json")["history"]
    result["credit_reporting_dates"] = sum(row["date"].startswith("2013-") for row in credit)
    assert result["credit_reporting_dates"] == 248

    replay = load(public / "chart-replay/markets.json")["markets"]
    result["replay"] = {row["ticker"]: sum(bar["date"].startswith("2013-") for bar in row["bars"]) for row in replay}
    assert result["replay"] == {"^KS11": 247, "GC=F": 252}
    semiconductor = load(public / "semiconductor/index.json")["stocks"]
    result["semiconductor_tickers_with_2013_prices"] = sum(any(p["date"].startswith("2013-") for p in row["history"]) for row in semiconductor)

    listings, periods = 0, 0
    for path in sorted((source / "stock-information").glob("[0-9a-f].json.gz")):
        for ticker, row in load(path).items():
            reported = [entry for entry in row["financials"] if entry["period_end"].startswith("2013-")]
            if reported:
                snapshot = load(public / "stock-information" / (quote(ticker, safe="").replace("%", "~") + ".json"))
                assert reported == [entry for entry in snapshot["financials"] if entry["period_end"].startswith("2013-")], ticker
                listings += 1
                periods += len(reported)
    assert (listings, periods) == (2366, 10493), (listings, periods)
    result["financials"] = {"listings": listings, "reported_periods": periods}
    result["daily_source_manifest_sha256"] = sha256(json.dumps(input_hashes, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public", type=Path, default=ROOT / "frontend/public/data")
    args = parser.parse_args()
    summary = audit(args.public)
    write_json(ROOT / "data/information-audit/2013/local-validation.json", summary)
    print(json.dumps(summary), flush=True)
