"""Validate the daily new-high archive and publish JSON without fetching prices."""

from __future__ import annotations

import argparse
import json
import math
import re
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = PROJECT_ROOT / "data" / "new-highs"
GENERATED_DIR = PROJECT_ROOT / "data" / "generated"
FRONTEND_DATA_DIR = PROJECT_ROOT / "frontend" / "public" / "data"
HIGH_TYPES = {"52_week", "all_time"}


class NewHighDataError(ValueError):
    """A source file cannot be published as a daily report."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise NewHighDataError(message)


def nonempty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def read_json(path: Path) -> dict[str, Any]:
    def reject_nonfinite(value: str) -> None:
        raise ValueError(f"non-finite JSON number: {value}")

    def finite_float(value: str) -> float:
        number = float(value)
        if not math.isfinite(number):
            reject_nonfinite(value)
        return number

    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"), parse_constant=reject_nonfinite, parse_float=finite_float)
    except (OSError, ValueError) as exc:
        raise NewHighDataError(f"{path}: {exc}") from exc
    require(isinstance(payload, dict), f"{path}: expected a JSON object")
    require(type(payload.get("schema_version")) is int and payload["schema_version"] == 1,
            f"{path}: schema_version must be 1")
    return payload


def load_markets(source_dir: Path) -> list[dict[str, Any]]:
    path = source_dir / "markets.json"
    markets = read_json(path).get("markets")
    require(isinstance(markets, list) and bool(markets), f"{path}: markets must be a nonempty list")
    seen: set[str] = set()
    for market in markets:
        require(isinstance(market, dict), f"{path}: each market must be an object")
        market_id = market.get("id")
        require(isinstance(market_id, str) and re.fullmatch(r"[a-z][a-z0-9-]*", market_id) is not None,
                f"{path}: invalid market id: {market_id!r}")
        require(market_id not in seen, f"{path}: duplicate market: {market_id}")
        seen.add(market_id)
        for field in ("label", "timezone", "default_exchange"):
            require(nonempty_text(market.get(field)), f"{path}: {market_id}.{field} is required")
        try:
            ZoneInfo(market["timezone"])
        except (ValueError, ZoneInfoNotFoundError) as exc:
            raise NewHighDataError(f"{path}: {market_id}.timezone must be a valid IANA timezone") from exc
        exchanges = market.get("exchanges")
        require(isinstance(exchanges, list) and bool(exchanges), f"{path}: {market_id}.exchanges must be a nonempty list")
        exchange_ids: set[str] = set()
        for exchange in exchanges:
            require(isinstance(exchange, dict), f"{path}: each exchange must be an object")
            exchange_id = exchange.get("id")
            require(isinstance(exchange_id, str) and re.fullmatch(r"[A-Z][A-Z0-9_-]*", exchange_id) is not None,
                    f"{path}: invalid exchange id: {exchange_id!r}")
            require(nonempty_text(exchange.get("label")), f"{path}: exchange label is required")
            require(exchange_id not in exchange_ids, f"{path}: duplicate exchange: {exchange_id}")
            exchange_ids.add(exchange_id)
        require(market["default_exchange"] == "all" or market["default_exchange"] in exchange_ids,
                f"{path}: default_exchange must be all or a registered exchange for {market_id}")
    return markets


def validate_report(payload: dict[str, Any], path: Path, reports_dir: Path,
                    markets: dict[str, dict[str, Any]]) -> None:
    relative = path.relative_to(reports_dir)
    require(len(relative.parts) == 2, f"{path}: expected reports/{{market}}/{{YYYY-MM-DD}}.json")
    market_id = payload.get("market")
    require(isinstance(market_id, str) and market_id in markets, f"{path}: unknown market: {market_id!r}")
    require(relative.parts[0] == market_id, f"{path}: market does not match its folder")
    report_date = payload.get("date")
    require(isinstance(report_date, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", report_date) is not None,
            f"{path}: date must be YYYY-MM-DD")
    try:
        date.fromisoformat(report_date)
    except ValueError as exc:
        raise NewHighDataError(f"{path}: invalid calendar date: {report_date}") from exc
    require(path.stem == report_date, f"{path}: date does not match its filename")
    if "summary" in payload:
        require(isinstance(payload["summary"], str), f"{path}: summary must be a string")
    sources = payload.get("sources", [])
    require(isinstance(sources, list), f"{path}: sources must be a list")
    for source in sources:
        require(isinstance(source, dict) and nonempty_text(source.get("label")), f"{path}: source label is required")
        if "url" in source:
            url = source["url"]
            require(nonempty_text(url) and not any(char.isspace() or ord(char) < 32 for char in url),
                    f"{path}: source URL must be an absolute HTTP(S) URL")
            try:
                parsed = urlsplit(url)
                valid = parsed.scheme in {"http", "https"} and bool(parsed.hostname) and not parsed.username and not parsed.password
            except ValueError:
                valid = False
            require(valid, f"{path}: source URL must be an absolute HTTP(S) URL without credentials")
    entries = payload.get("entries")
    require(isinstance(entries, list), f"{path}: entries must be a list (use [] for a confirmed zero-result day)")
    known_exchanges = {exchange["id"] for exchange in markets[market_id]["exchanges"]}
    tickers: set[str] = set()
    for position, entry in enumerate(entries, start=1):
        prefix = f"{path}: entry {position}"
        require(isinstance(entry, dict), f"{prefix} must be an object")
        for field in ("ticker", "name", "exchange", "category", "high_type", "reason"):
            require(nonempty_text(entry.get(field)), f"{prefix}: {field} is required")
        ticker = entry["ticker"]
        require(ticker == ticker.strip(), f"{prefix}: ticker must not have surrounding whitespace")
        require(ticker.upper() not in tickers, f"{prefix}: duplicate ticker: {ticker}; use all_time once if both apply")
        tickers.add(ticker.upper())
        require(entry["exchange"] in known_exchanges, f"{prefix}: unknown exchange: {entry['exchange']}")
        require(entry["high_type"] in HIGH_TYPES, f"{prefix}: high_type must be 52_week or all_time")
        if "description" in entry:
            require(isinstance(entry["description"], str), f"{prefix}: description must be a string")
        change_pct = entry.get("change_pct")
        require(change_pct is None or type(change_pct) is int or (type(change_pct) is float and math.isfinite(change_pct)),
                f"{prefix}: change_pct must be a finite number or null")
    category_reasons = payload.get("category_reasons", {})
    require(isinstance(category_reasons, dict), f"{path}: category_reasons must be an object")
    categories = {entry["category"] for entry in entries}
    for category, reason in category_reasons.items():
        require(category in categories and nonempty_text(reason),
                f"{path}: category_reasons keys must match entry categories and values must be nonempty strings")


def count_entries(entries: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "total": len(entries),
        "high_52_week": sum(entry["high_type"] == "52_week" for entry in entries),
        "high_all_time": sum(entry["high_type"] == "all_time" for entry in entries),
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def generate_new_high_data(source_dir: Path = SOURCE_DIR, output_dir: Path = GENERATED_DIR,
                           frontend_data_dir: Path | None = FRONTEND_DATA_DIR) -> dict[str, Any]:
    """Validate all reports first, then write only the new-highs output namespace."""
    markets = load_markets(source_dir)
    markets_by_id = {market["id"]: market for market in markets}
    reports_dir = source_dir / "reports"
    reports = []
    for path in sorted(reports_dir.rglob("*.json")):
        payload = read_json(path)
        validate_report(payload, path, reports_dir, markets_by_id)
        reports.append(payload)
    reports.sort(key=lambda report: (-date.fromisoformat(report["date"]).toordinal(), report["market"]))
    summaries = []
    for report in reports:
        entries = report["entries"]
        summaries.append({
            "market": report["market"],
            "date": report["date"],
            "counts": count_entries(entries),
            "exchanges": {
                exchange["id"]: count_entries([entry for entry in entries if entry["exchange"] == exchange["id"]])
                for exchange in markets_by_id[report["market"]]["exchanges"]
            },
        })
    index = {"schema_version": 1, "markets": markets, "reports": summaries}
    destinations = [output_dir]
    if frontend_data_dir is not None and frontend_data_dir.resolve() != output_dir.resolve():
        destinations.append(frontend_data_dir)
    for destination in destinations:
        namespace = destination / "new-highs"
        for report in reports:
            write_json(namespace / report["market"] / f"{report['date']}.json", report)
        # Publish the index after its referenced reports are present.
        write_json(namespace / "index.json", index)
    return index


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=SOURCE_DIR)
    parser.add_argument("--output-dir", type=Path, default=GENERATED_DIR)
    parser.add_argument("--frontend-data-dir", type=Path, default=FRONTEND_DATA_DIR)
    parser.add_argument("--copy-to-frontend", action=argparse.BooleanOptionalAction, default=True)
    args = parser.parse_args()
    try:
        index = generate_new_high_data(args.source_dir, args.output_dir,
                                       args.frontend_data_dir if args.copy_to_frontend else None)
    except NewHighDataError as exc:
        parser.exit(1, f"New-high data validation failed: {exc}\n")
    print(f"Published {len(index['reports'])} daily new-high reports across {len(index['markets'])} markets.")


if __name__ == "__main__":
    main()
