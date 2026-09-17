"""Validate and publish the daily turnover top-30 archive."""

from __future__ import annotations

import argparse
import json
import math
import re
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from generate_new_high_data import load_markets, nonempty_text, require


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = PROJECT_ROOT / "data" / "turnover"
GENERATED_DIR = PROJECT_ROOT / "data" / "generated"
FRONTEND_DATA_DIR = PROJECT_ROOT / "frontend" / "public" / "data"


class TurnoverDataError(ValueError):
    """A source file cannot be published as a daily turnover report."""


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"), parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    except (OSError, ValueError) as exc:
        raise TurnoverDataError(f"{path}: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise TurnoverDataError(f"{path}: expected a schema_version 1 JSON object")
    return payload


def _finite(value: Any, *, positive: bool = False) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and (not positive or value > 0)


def validate_report(payload: dict[str, Any], path: Path, reports_dir: Path,
                    markets: dict[str, dict[str, Any]]) -> None:
    relative = path.relative_to(reports_dir)
    if len(relative.parts) != 2:
        raise TurnoverDataError(f"{path}: expected reports/{{market}}/{{YYYY-MM-DD}}.json")
    market_id, report_date = payload.get("market"), payload.get("date")
    if market_id not in markets or relative.parts[0] != market_id:
        raise TurnoverDataError(f"{path}: unknown or mismatched market")
    if not isinstance(report_date, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", report_date):
        raise TurnoverDataError(f"{path}: date must be YYYY-MM-DD")
    try:
        date.fromisoformat(report_date)
    except ValueError as exc:
        raise TurnoverDataError(f"{path}: invalid date") from exc
    if path.stem != report_date:
        raise TurnoverDataError(f"{path}: date does not match filename")

    entries = payload.get("entries")
    if not isinstance(entries, list) or len(entries) > 30:
        raise TurnoverDataError(f"{path}: entries must be a list of at most 30 stocks")
    known_exchanges = {item["id"] for item in markets[market_id]["exchanges"]}
    seen: set[str] = set()
    previous_turnover: float | None = None
    for position, entry in enumerate(entries, start=1):
        prefix = f"{path}: entry {position}"
        if not isinstance(entry, dict) or entry.get("rank") != position:
            raise TurnoverDataError(f"{prefix}: rank must be contiguous and match list order")
        for field in ("ticker", "name", "exchange", "currency", "sector", "industry"):
            if not nonempty_text(entry.get(field)):
                raise TurnoverDataError(f"{prefix}: {field} is required")
        ticker = entry["ticker"].upper()
        if ticker in seen:
            raise TurnoverDataError(f"{prefix}: duplicate ticker")
        seen.add(ticker)
        if entry["exchange"] not in known_exchanges:
            raise TurnoverDataError(f"{prefix}: unknown exchange")
        if not re.fullmatch(r"[A-Z]{3}", entry["currency"]):
            raise TurnoverDataError(f"{prefix}: currency must be a three-letter uppercase code")
        if not _finite(entry.get("price"), positive=True) or not _finite(entry.get("turnover"), positive=True):
            raise TurnoverDataError(f"{prefix}: price and turnover must be positive finite numbers")
        if entry.get("change_pct") is not None and not _finite(entry["change_pct"]):
            raise TurnoverDataError(f"{prefix}: change_pct must be finite or null")
        if entry.get("market_cap") is not None and not _finite(entry["market_cap"], positive=True):
            raise TurnoverDataError(f"{prefix}: market_cap must be positive or null")
        if previous_turnover is not None and entry["turnover"] > previous_turnover:
            raise TurnoverDataError(f"{prefix}: entries must be sorted by turnover descending")
        previous_turnover = entry["turnover"]
        if "logo_url" in entry:
            url = entry["logo_url"]
            parsed = urlsplit(url) if isinstance(url, str) else None
            if not parsed or parsed.scheme != "https" or parsed.hostname != "s3-symbol-logo.tradingview.com":
                raise TurnoverDataError(f"{prefix}: logo_url must use the TradingView logo host")

    sources = payload.get("sources", [])
    if not isinstance(sources, list):
        raise TurnoverDataError(f"{path}: sources must be a list")
    for source in sources:
        if not isinstance(source, dict) or not nonempty_text(source.get("label")):
            raise TurnoverDataError(f"{path}: source label is required")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def generate_turnover_data(source_dir: Path = SOURCE_DIR, output_dir: Path = GENERATED_DIR,
                           frontend_data_dir: Path | None = FRONTEND_DATA_DIR) -> dict[str, Any]:
    try:
        markets = load_markets(source_dir)
    except ValueError as exc:
        raise TurnoverDataError(str(exc)) from exc
    markets_by_id = {market["id"]: market for market in markets}
    reports_dir = source_dir / "reports"
    reports = []
    for path in sorted(reports_dir.rglob("*.json")) if reports_dir.exists() else []:
        payload = read_json(path)
        validate_report(payload, path, reports_dir, markets_by_id)
        reports.append(payload)
    reports.sort(key=lambda report: (-date.fromisoformat(report["date"]).toordinal(), report["market"]))
    index: dict[str, Any] = {
        "schema_version": 1,
        "markets": markets,
        "reports": [{
            "market": report["market"], "date": report["date"], "count": len(report["entries"]),
            "total_turnover": sum(entry["turnover"] for entry in report["entries"]),
            "currency": report["entries"][0]["currency"] if report["entries"] else None,
        } for report in reports],
    }
    status_path = source_dir / "refresh-status.json"
    if status_path.exists():
        statuses = read_json(status_path).get("markets")
        if not isinstance(statuses, dict):
            raise TurnoverDataError(f"{status_path}: markets must be an object")
        index["refresh"] = statuses
    destinations = [output_dir]
    if frontend_data_dir is not None and frontend_data_dir.resolve() != output_dir.resolve():
        destinations.append(frontend_data_dir)
    for destination in destinations:
        namespace = destination / "turnover"
        for report in reports:
            write_json(namespace / report["market"] / f"{report['date']}.json", report)
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
        index = generate_turnover_data(args.source_dir, args.output_dir,
                                       args.frontend_data_dir if args.copy_to_frontend else None)
    except TurnoverDataError as exc:
        parser.exit(1, f"Turnover data validation failed: {exc}\n")
    print(f"Published {len(index['reports'])} daily turnover reports across {len(index['markets'])} markets.")


if __name__ == "__main__":
    main()
