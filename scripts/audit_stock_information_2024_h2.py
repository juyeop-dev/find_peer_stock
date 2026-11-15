"""Validate every published detail stock and record honest H2-2024 coverage."""
from collections import Counter
from datetime import datetime, timezone
import gzip
import hashlib
import json
import math

import stock_chart_history as charts
import stock_information as information

START, END = "2024-07-01", "2024-12-31"
SCOPE = "2024-h2"
COVERED_STATUS = "covers_h2_2024"
PERIODS_KEY = "h2_financial_periods"


def packs(folder, shard=None):
    result = {}
    for path in sorted(folder.glob(f"{shard}.json.gz" if shard is not None else "*.json.gz")):
        entries = json.loads(gzip.decompress(path.read_bytes()))
        assert not set(result).intersection(entries), f"Duplicate packed listing: {path}"
        result.update(entries)
    return result


def iter_listing_sources(rows):
    groups = {shard: [] for shard in '0123456789abcdef'}
    for row in rows:
        groups[hashlib.sha256(row['ticker'].encode()).hexdigest()[0]].append(row)
    for shard, group in groups.items():
        info = packs(information.PACKS, shard)
        history = packs(charts.PACKS, shard)
        for values in [info, history]:
            assert all(hashlib.sha256(ticker.encode()).hexdigest()[0] == shard for ticker in values), f'Misplaced or duplicate listing in shard {shard}'
        del values
        for row in group:
            yield row, info.get(row['ticker']), history.get(row['ticker'], {})
        del info, history


def main():
    roster = charts.roster()
    results = []
    for row, value, history in iter_listing_sources(roster):
        ticker = row["ticker"]
        assert value and value["ticker"] == ticker, f"Missing information: {ticker}"
        statements = value["financials"]
        for statement in statements:
            assert statement["type"] in {"annual", "quarterly", "semiannual"} and statement["currency"] and statement["source"]
            assert information.START <= statement["period_end"] <= datetime.now(timezone.utc).date().isoformat()
            for key in information.METRICS:
                number = statement.get(key)
                assert number is None or type(number) in {int, float} and math.isfinite(number), (ticker, key)
        keys = [(s["type"], s["period_end"], s["currency"]) for s in statements]
        assert len(keys) == len(set(keys)), f"Duplicate financial period: {ticker}"
        old = [s for s in statements if START <= s["period_end"] <= END]
        prices = history.get("prices", [])
        if prices:
            assert history["currency"] and history["source"]
            dates = [point[0] for point in prices]
            assert dates == sorted(set(dates)), ticker
            assert all(type(n) in {int, float} and math.isfinite(n) and n > 0 for point in prices for n in point[1:]), ticker
            for previous in history.get("prior_snapshots", []):
                assert previous["ticker"] == ticker and previous["currency"] and previous["source"]
                prior_dates = [point[0] for point in previous["prices"]]
                assert prior_dates == sorted(set(prior_dates)), ticker
                assert all(type(n) in {int, float} and math.isfinite(n) and n > 0 for point in previous["prices"] for n in point[1:]), ticker
        status = "missing_history" if len(prices) < 2 else COVERED_STATUS if prices[0][0] <= START else "later_listing" if history.get("first_trade_date") and history["first_trade_date"] > START else "source_limited"
        results.append({**row, "history_status": status, "first_price": prices[0][0] if prices else None,
            "last_price": prices[-1][0] if prices else None, "first_trade_date": history.get("first_trade_date"),
            PERIODS_KEY: len(old), "annual_periods": sum(s["type"] == "annual" for s in old),
            "quarterly_periods": sum(s["type"] == "quarterly" for s in old),
            "revenue_available": any(s.get("revenue") is not None for s in old),
            "operating_income_available": any(s.get("operating_income") is not None for s in old)})
    order = {row['ticker']: index for index, row in enumerate(roster)}
    results.sort(key=lambda row: order[row['ticker']])
    audit = information.AUDIT / SCOPE
    charts.write_json(audit / "coverage.json", {"start": START, "end": END, "total": len(roster), "checked": len(results),
        "histories": dict(Counter(row["history_status"] for row in results)),
        "financials_available": sum(row[PERIODS_KEY] > 0 for row in results),
        "revenue_available": sum(row["revenue_available"] for row in results),
        "operating_income_available": sum(row["operating_income_available"] for row in results),
        "financials_unavailable": sum(row[PERIODS_KEY] == 0 for row in results),
        "quarterly_reports": sum(row["quarterly_periods"] for row in results),
        "by_market": dict(Counter(row["market"] for row in results)), "validated_at": datetime.now(timezone.utc).isoformat()})
    charts.write_json(audit / "coverage-results.json", results)
    charts.write_json(audit / "coverage-exceptions.json", [row for row in results if row["history_status"] in {"missing_history", "source_limited"} or not row[PERIODS_KEY]])
    print((audit / "coverage.json").read_text(encoding="utf-8"), flush=True)


if __name__ == "__main__":
    main()
