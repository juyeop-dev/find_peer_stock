"""Build monthly stock aggregates from validated daily calendar reports."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def turnover_by_currency(entries: list[dict[str, Any]]) -> dict[str, float]:
    totals: dict[str, float] = {}
    for entry in entries:
        currency = entry.get("turnover_currency", entry["currency"])
        totals[currency] = totals.get(currency, 0) + entry["turnover"]
    return dict(sorted(totals.items()))


def build_history(reports: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    years: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
    for report in sorted(reports, key=lambda item: item["date"]):
        month = report["date"][:7]
        months = years.setdefault((report["market"], month[:4]), {})
        stocks = months.setdefault(month, {})
        for entry in report["entries"]:
            ticker = entry["ticker"].upper()
            stock = stocks.setdefault(ticker, {
                "ticker": ticker, "name": entry["name"], "exchange": entry["exchange"],
                "category": "", "dates": [], "high_52_week": 0, "high_all_time": 0,
                "turnover_by_currency": {},
            })
            # Keep the most recently recorded name and industry in this month.
            stock["name"] = entry["name"]
            stock["category"] = entry.get("category", entry.get("industry", ""))
            stock["dates"].append(report["date"])
            if kind == "new-highs":
                stock["high_all_time" if entry["high_type"] == "all_time" else "high_52_week"] += 1
            else:
                currency = entry.get("turnover_currency", entry["currency"])
                totals = stock["turnover_by_currency"]
                totals[currency] = totals.get(currency, 0) + entry["turnover"]
    return [{
        "schema_version": 1, "kind": kind, "market": market, "year": year,
        "months": [{"month": month, "stocks": [stocks[ticker] for ticker in sorted(stocks)]}
                   for month, stocks in sorted(months.items())],
    } for (market, year), months in sorted(years.items())]


def publish_history(namespace: Path, history: list[dict[str, Any]]) -> None:
    for payload in history:
        path = namespace / "history" / payload["market"] / f"{payload['year']}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n",
                        encoding="utf-8")
