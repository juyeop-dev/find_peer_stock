"""Validate the daily new-high archive and publish JSON without fetching prices."""

from __future__ import annotations

import argparse
import copy
import json
import math
import re
from datetime import date, time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from period_returns import validate_period_returns
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = PROJECT_ROOT / "data" / "new-highs"
GENERATED_DIR = PROJECT_ROOT / "data" / "generated"
FRONTEND_DATA_DIR = PROJECT_ROOT / "frontend" / "public" / "data"
HIGH_TYPES = {"52_week", "all_time"}
MARKET_CAP_FIELDS = (
    "market_cap",
    "market_cap_currency",
    "market_cap_usd",
    "market_cap_source",
    "market_cap_fetched_at",
)


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
        if "refresh_after" in market:
            require(isinstance(market["refresh_after"], str) and
                    re.fullmatch(r"\d{2}:\d{2}", market["refresh_after"]) is not None,
                    f"{path}: refresh_after must be HH:MM")
            try:
                time.fromisoformat(market["refresh_after"])
            except ValueError as exc:
                raise NewHighDataError(f"{path}: invalid refresh_after") from exc
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
        if "peers" in entry:
            require(isinstance(entry["peers"], list), f"{prefix}: peers must be a list")
            peer_tickers: set[str] = set()
            for peer in entry["peers"]:
                require(isinstance(peer, dict) and nonempty_text(peer.get("ticker")) and
                        nonempty_text(peer.get("name")), f"{prefix}: each peer needs a ticker and name")
                require(peer["ticker"] != ticker and peer["ticker"] not in peer_tickers,
                        f"{prefix}: duplicate or self-referencing peer")
                peer_tickers.add(peer["ticker"])
        change_pct = entry.get("change_pct")
        require(change_pct is None or type(change_pct) is int or (type(change_pct) is float and math.isfinite(change_pct)),
                f"{prefix}: change_pct must be a finite number or null")
        try:
            validate_period_returns(entry, report_date, prefix)
        except ValueError as exc:
            raise NewHighDataError(str(exc)) from exc
        for field in ("session_open", "session_close"):
            if field in entry:
                value = entry[field]
                require((type(value) is int and value > 0) or
                        (type(value) is float and math.isfinite(value) and value > 0),
                        f"{prefix}: {field} must be a positive finite number")
        if "session_volume" in entry:
            volume = entry["session_volume"]
            require(type(volume) in (int, float) and math.isfinite(volume) and volume > 0,
                    f"{prefix}: session_volume must be a positive finite number")
        if "currency" in entry:
            require(isinstance(entry["currency"], str) and re.fullmatch(r"[A-Z]{3}", entry["currency"]) is not None,
                    f"{prefix}: currency must be a three-letter uppercase code")
    category_reasons = payload.get("category_reasons", {})
    require(isinstance(category_reasons, dict), f"{path}: category_reasons must be an object")
    categories = {entry["category"] for entry in entries}
    for category, reason in category_reasons.items():
        require(category in categories and nonempty_text(reason),
                f"{path}: category_reasons keys must match entry categories and values must be nonempty strings")
    source_metadata = payload.get("source_metadata")
    if source_metadata is not None:
        require(isinstance(source_metadata, dict), f"{path}: source_metadata must be an object")
        previous_sessions = source_metadata.get("previous_session_by_exchange")
        if previous_sessions is not None:
            scanner_exchanges = source_metadata.get("scanner_exchanges")
            latest_sessions = source_metadata.get("latest_session_by_exchange")
            require(isinstance(scanner_exchanges, list) and bool(scanner_exchanges) and
                    all(nonempty_text(exchange) for exchange in scanner_exchanges) and
                    len(scanner_exchanges) == len(set(scanner_exchanges)),
                    f"{path}: scanner_exchanges must be a nonempty unique string list")
            require(isinstance(previous_sessions, dict) and
                    set(previous_sessions) == set(scanner_exchanges),
                    f"{path}: previous sessions must cover every scanner exchange")
            require(isinstance(latest_sessions, dict) and set(latest_sessions) == set(scanner_exchanges) and
                    all(value == report_date for value in latest_sessions.values()),
                    f"{path}: latest sessions must match the report date for every scanner exchange")
            current_day = date.fromisoformat(report_date)
            for exchange, value in previous_sessions.items():
                require(isinstance(value, str), f"{path}: invalid previous session for {exchange}")
                try:
                    previous_day = date.fromisoformat(value)
                except ValueError as exc:
                    raise NewHighDataError(f"{path}: invalid previous session for {exchange}") from exc
                require(previous_day < current_day,
                        f"{path}: previous session must precede report date for {exchange}")


def count_entries(entries: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "total": len(entries),
        "high_52_week": sum(entry["high_type"] == "52_week" for entry in entries),
        "high_all_time": sum(entry["high_type"] == "all_time" for entry in entries),
    }


def confirmed_market_closures(reports: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Derive weekday closures only from a source-proven gap between sessions.

    Missing reports alone are never treated as closures. For multi-exchange
    markets, a date is closed only when every covered exchange skipped it.
    """
    closures: set[tuple[str, date]] = set()
    recorded_sessions = {(report["market"], date.fromisoformat(report["date"])) for report in reports}
    for report in reports:
        metadata = report.get("source_metadata")
        if not isinstance(metadata, dict):
            continue
        previous_sessions = metadata.get("previous_session_by_exchange")
        scanner_exchanges = metadata.get("scanner_exchanges")
        if not isinstance(previous_sessions, dict) or not isinstance(scanner_exchanges, list):
            continue
        current_day = date.fromisoformat(report["date"])
        gaps: list[set[date]] = []
        for exchange in scanner_exchanges:
            previous_day = date.fromisoformat(previous_sessions[exchange])
            gap = {
                date.fromordinal(ordinal)
                for ordinal in range(previous_day.toordinal() + 1, current_day.toordinal())
                if date.fromordinal(ordinal).weekday() < 5
            }
            gaps.append(gap)
        if gaps:
            closures.update((report["market"], day) for day in set.intersection(*gaps))
    closures.difference_update(recorded_sessions)
    return [
        {"market": market, "date": closed_day.isoformat(), "label": "휴장"}
        for market, closed_day in sorted(closures, key=lambda item: (-item[1].toordinal(), item[0]))
    ]


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def load_published_market_caps(output_dir: Path) -> dict[tuple[str, str, str], dict[str, Any]]:
    """Keep the last fetched caps when this archive-only generator runs without a network fetch."""
    result: dict[tuple[str, str, str], dict[str, Any]] = {}
    namespace = output_dir / "new-highs"
    if not namespace.exists():
        return result
    for path in namespace.glob("*/*.json"):
        try:
            report = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            continue
        if not isinstance(report, dict) or not isinstance(report.get("entries"), list):
            continue
        market = report.get("market")
        report_date = report.get("date")
        if not isinstance(market, str) or not isinstance(report_date, str):
            continue
        for entry in report["entries"]:
            if not isinstance(entry, dict) or not isinstance(entry.get("ticker"), str):
                continue
            value = entry.get("market_cap")
            currency = entry.get("market_cap_currency")
            if (type(value) not in {int, float} or not math.isfinite(value) or value <= 0 or
                    not isinstance(currency, str) or re.fullmatch(r"[A-Z]{3}", currency) is None):
                continue
            cap = {field: entry[field] for field in MARKET_CAP_FIELDS if field in entry}
            value_usd = cap.get("market_cap_usd")
            if value_usd is not None and (type(value_usd) not in {int, float} or
                                          not math.isfinite(value_usd) or value_usd <= 0):
                cap["market_cap_usd"] = None
            result[(market, report_date, entry["ticker"])] = cap
    return result


def publish_reports(reports: list[dict[str, Any]], output_dir: Path,
                    market_caps: dict[str, Any] | None,
                    market_cap_fetched_at: str | None,
                    peers_by_ticker: dict[str, list[dict[str, str]]]) -> list[dict[str, Any]]:
    existing_caps = load_published_market_caps(output_dir)
    published = copy.deepcopy(reports)
    for report in published:
        for entry in report["entries"]:
            if "peers" not in entry and entry["ticker"] in peers_by_ticker:
                entry["peers"] = copy.deepcopy(peers_by_ticker[entry["ticker"]])
            cap = (market_caps or {}).get(entry["ticker"])
            if cap is not None:
                entry.update({
                    "market_cap": cap.value,
                    "market_cap_currency": cap.currency,
                    "market_cap_usd": cap.value_usd,
                    "market_cap_source": cap.source,
                    "market_cap_fetched_at": market_cap_fetched_at,
                })
                continue
            saved = existing_caps.get((report["market"], report["date"], entry["ticker"]))
            if saved:
                entry.update(saved)
    return published


def generate_new_high_data(source_dir: Path = SOURCE_DIR, output_dir: Path = GENERATED_DIR,
                           frontend_data_dir: Path | None = FRONTEND_DATA_DIR, *,
                           market_caps: dict[str, Any] | None = None,
                           market_cap_fetched_at: str | None = None) -> dict[str, Any]:
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
    peer_path = source_dir / "peer-map.json"
    peers_by_ticker: dict[str, list[dict[str, str]]] = {}
    if peer_path.exists():
        peer_data = read_json(peer_path).get("peers_by_ticker")
        require(isinstance(peer_data, dict), f"{peer_path}: peers_by_ticker must be an object")
        for ticker, peers in peer_data.items():
            require(nonempty_text(ticker) and isinstance(peers, list) and bool(peers),
                    f"{peer_path}: invalid peers for {ticker!r}")
            seen: set[str] = set()
            for peer in peers:
                require(isinstance(peer, dict) and nonempty_text(peer.get("ticker")) and
                        nonempty_text(peer.get("name")), f"{peer_path}: invalid peer for {ticker}")
                require(peer["ticker"] != ticker and peer["ticker"] not in seen,
                        f"{peer_path}: duplicate or self-referencing peer for {ticker}")
                seen.add(peer["ticker"])
            peers_by_ticker[ticker] = peers
    published_reports = publish_reports(reports, output_dir, market_caps, market_cap_fetched_at, peers_by_ticker)
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
    index = {
        "schema_version": 1,
        "markets": markets,
        "reports": summaries,
        "closures": confirmed_market_closures(reports),
    }
    status_path = source_dir / "refresh-status.json"
    if status_path.exists():
        statuses = read_json(status_path).get("markets")
        require(isinstance(statuses, dict), f"{status_path}: markets must be an object")
        for market_id, status in statuses.items():
            require(market_id in markets_by_id and isinstance(status, dict),
                    f"{status_path}: unknown market or invalid refresh status")
            require(status.get("status") in {"updated", "pending", "error", "closed", "unsupported"},
                    f"{status_path}: invalid status for {market_id}")
        index["refresh"] = statuses
    destinations = [output_dir]
    if frontend_data_dir is not None and frontend_data_dir.resolve() != output_dir.resolve():
        destinations.append(frontend_data_dir)
    for destination in destinations:
        namespace = destination / "new-highs"
        for report in published_reports:
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
