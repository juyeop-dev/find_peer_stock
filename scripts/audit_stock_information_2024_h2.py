"""Validate every published detail stock and record honest H2-2024 coverage."""
from collections import Counter
from datetime import datetime, timezone
import gzip
import json
import math

import stock_chart_history as charts
import stock_information as information

START, END = "2024-07-01", "2024-12-31"


def packs(folder):
    result = {}
    for path in sorted(folder.glob("*.json.gz")):
        shard = json.loads(gzip.decompress(path.read_bytes()))
        assert not set(result).intersection(shard), f"Duplicate packed listing: {path}"
        result.update(shard)
    return result


def main():
    info = packs(information.PACKS)
    history = packs(charts.PACKS)
    roster = charts.roster()
    results = []
    for row in roster:
        ticker = row["ticker"]
        value = info.get(ticker)
        assert value and value["ticker"] == ticker, f"Missing information: {ticker}"
        statements = value["financials"]
        for statement in statements:
            assert statement["type"] in {"annual", "quarterly", "semiannual"} and statement["currency"] and statement["source"]
            assert START <= statement["period_end"] <= datetime.now(timezone.utc).date().isoformat()
            for key in information.METRICS:
                number = statement.get(key)
                assert number is None or type(number) in {int, float} and math.isfinite(number), (ticker, key)
        keys = [(s["type"], s["period_end"], s["currency"]) for s in statements]
        assert len(keys) == len(set(keys)), f"Duplicate financial period: {ticker}"
        old = [s for s in statements if START <= s["period_end"] <= END]
        prices = history.get(ticker, {}).get("prices", [])
        if prices:
            assert history[ticker]["currency"] and history[ticker]["source"]
            dates = [point[0] for point in prices]
            assert dates == sorted(set(dates)), ticker
            assert all(type(n) in {int, float} and math.isfinite(n) and n > 0 for point in prices for n in point[1:]), ticker
        status = "missing_history" if len(prices) < 2 else "covers_h2_2024" if prices[0][0] <= START else "later_listing" if history[ticker].get("first_trade_date") and history[ticker]["first_trade_date"] > START else "source_limited"
        results.append({**row, "history_status": status, "first_price": prices[0][0] if prices else None,
            "last_price": prices[-1][0] if prices else None, "first_trade_date": history.get(ticker, {}).get("first_trade_date"),
            "h2_financial_periods": len(old), "annual_periods": sum(s["type"] == "annual" for s in old),
            "quarterly_periods": sum(s["type"] == "quarterly" for s in old),
            "revenue_available": any(s.get("revenue") is not None for s in old),
            "operating_income_available": any(s.get("operating_income") is not None for s in old)})
    audit = information.AUDIT / "2024-h2"
    charts.write_json(audit / "coverage.json", {"start": START, "end": END, "total": len(roster), "checked": len(results),
        "histories": dict(Counter(row["history_status"] for row in results)),
        "financials_available": sum(row["h2_financial_periods"] > 0 for row in results),
        "revenue_available": sum(row["revenue_available"] for row in results),
        "operating_income_available": sum(row["operating_income_available"] for row in results),
        "financials_unavailable": sum(row["h2_financial_periods"] == 0 for row in results),
        "quarterly_reports": sum(row["quarterly_periods"] for row in results),
        "by_market": dict(Counter(row["market"] for row in results)), "validated_at": datetime.now(timezone.utc).isoformat()})
    charts.write_json(audit / "coverage-results.json", results)
    charts.write_json(audit / "coverage-exceptions.json", [row for row in results if row["history_status"] in {"missing_history", "source_limited"} or not row["h2_financial_periods"]])
    print((audit / "coverage.json").read_text(encoding="utf-8"), flush=True)


if __name__ == "__main__":
    main()
