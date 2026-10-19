"""Publish observed calendar closing prices for every archived stock, without external requests."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
CURRENCIES = {"korea": "KRW", "us": "USD", "japan": "JPY", "taiwan": "TWD", "china": "CNY", "europe": "EUR"}


def calendar_stocks(reports: list[tuple[str, dict]]) -> list[dict]:
    stocks = {}
    for kind, report in sorted(reports, key=lambda item: (item[1]["date"], item[0])):
        market, day = report["market"], report["date"]
        for entry in report["entries"]:
            ticker = entry["ticker"].upper()
            stock = stocks.setdefault((market, ticker), {"schema_version": 1, "market": market, "ticker": ticker, "prices": {}})
            close = entry.get("price") if kind == "turnover" else entry.get("session_close")
            currency = entry.get("currency") or {"LSE": "GBP", "SIX": "CHF"}.get(entry["exchange"], CURRENCIES[market])
            if type(close) not in (int, float) or close <= 0:
                continue
            # Turnover has precedence on the same trading date. Never combine currencies.
            stock["prices"][(day, currency)] = {"date": day, "close": close, "currency": currency}
    result = []
    for _, stock in sorted(stocks.items()):
        prices = stock.pop("prices")
        stock["history"] = [prices[key] for key in sorted(prices)]
        result.append(stock)
    return result


def publish(source: Path = ROOT / "data", output: Path = ROOT / "frontend/public/data/calendar-stocks") -> int:
    reports = []
    for kind in ("new-highs", "turnover"):
        for path in sorted((source / kind / "reports").rglob("*.json")):
            reports.append((kind, json.loads(path.read_text(encoding="utf-8-sig"))))
    stocks = calendar_stocks(reports)
    for stock in stocks:
        # Use URL-safe filenames without percent signs so static hosts do not
        # decode a colon into a different filename (and Windows can store them).
        path = output / stock["market"] / f"{quote(stock['ticker'], safe='').replace('%', '~')}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        content = json.dumps(stock, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n"
        if not path.exists() or path.read_text(encoding="utf-8") != content:
            path.write_text(content, encoding="utf-8")
    return len(stocks)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "data")
    parser.add_argument("--output", type=Path, default=ROOT / "frontend/public/data/calendar-stocks")
    args = parser.parse_args()
    print(f"Published calendar price histories for {publish(args.source, args.output)} stocks.")
