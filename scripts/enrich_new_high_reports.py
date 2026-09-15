"""Fill saved new-high entries with session prices and industry-based reasons."""

from __future__ import annotations

import argparse
import copy
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from backfill_tradingview_new_highs import default_max_offset, historical_bar, scan_historical
from backfill_korean_new_highs import history_url, parse_history, request_with_retry
from generate_new_high_data import SOURCE_DIR, load_markets, read_json, validate_report
from new_high_sources.tradingview import _CONFIG, _number, _text, TradingViewSourceError
from refresh_new_highs import atomic_json


DEFAULT_REASON = "신고가 배경 미확인"


def industry_reason(entry: dict[str, Any]) -> str:
    sector = entry["category"].strip()
    industry = "업종 정보 미확인"
    description = entry.get("description")
    if isinstance(description, str) and " · " in description:
        candidate = description.rsplit(" · ", 1)[1].strip()
        if candidate:
            industry = candidate
    return f"업종: {sector} · {industry}"


def matching_bar(row: dict[str, Any], report_date: date, max_offset: int,
                 timezone_name: str) -> dict[str, Any]:
    matches = []
    for offset in range(max_offset + 1):
        bar = historical_bar(row, offset, timezone_name)
        if bar is not None and bar["date"] == report_date:
            matches.append(bar)
    if len(matches) != 1:
        raise TradingViewSourceError(
            f"{row['symbol']}: expected one historical bar for {report_date}, found {len(matches)}"
        )
    bar = matches[0]
    for field in ("open", "close"):
        if not _number(bar[field]) or bar[field] <= 0:
            raise TradingViewSourceError(f"{row['symbol']}: invalid historical {field} for {report_date}")
    return bar


def korean_session_prices(entry: dict[str, Any], report_date: date, timeout: float) -> tuple[float, float]:
    ticker = entry.get("ticker")
    if not _text(ticker):
        raise TradingViewSourceError("Korean entry missing ticker")
    code = str(ticker).split(".", 1)[0]
    raw = request_with_retry(history_url(code, report_date, report_date), timeout)
    history = parse_history(raw, code=code, start=report_date, end=report_date)
    row = history.get(report_date)
    if row is None or any(not _number(row[index]) or row[index] <= 0 for index in (1, 4)):
        raise TradingViewSourceError(f"KRX:{code}: missing valid prices for {report_date}")
    return row[1], row[4]


def enrich_reports(source_dir: Path = SOURCE_DIR, *, market_ids: set[str] | None = None,
                   start: date | None = None, end: date | None = None,
                   timeout: float = 30, page_size: int = 500,
                   now: datetime | None = None) -> list[Path]:
    markets = {market["id"]: market for market in load_markets(source_dir)}
    if market_ids and not market_ids <= markets.keys():
        raise ValueError("Unknown market in --market")
    reports_dir = source_dir / "reports"
    selected: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted(reports_dir.rglob("*.json")):
        report = read_json(path)
        report_date = date.fromisoformat(report["date"])
        if market_ids and report["market"] not in market_ids:
            continue
        if start and report_date < start or end and report_date > end:
            continue
        if any("session_close" not in entry or "currency" not in entry or
               entry.get("reason") == DEFAULT_REASON for entry in report["entries"]):
            selected.append((path, report))
    grouped: dict[str, list[tuple[Path, dict[str, Any]]]] = {}
    for item in selected:
        grouped.setdefault(item[1]["market"], []).append(item)

    updated: list[tuple[Path, dict[str, Any]]] = []
    for market_id, reports in grouped.items():
        if market_id not in _CONFIG:
            raise TradingViewSourceError(f"No historical price source for market: {market_id}")
        timezone_name = markets[market_id]["timezone"]
        local_today = (now or datetime.now(ZoneInfo(timezone_name))).astimezone(ZoneInfo(timezone_name)).date()
        oldest = min(date.fromisoformat(report["date"]) for _, report in reports)
        max_offset = default_max_offset(oldest, local_today)
        needed_symbols = {
            entry.get("source_symbol")
            for _, report in reports for entry in report["entries"]
            if ("session_close" not in entry or "currency" not in entry) and market_id != "korea"
        }
        if any(not _text(symbol) for symbol in needed_symbols):
            raise TradingViewSourceError(f"{market_id}: an entry missing session price has no source_symbol")
        rows = scan_historical(
            market_id, max_offset, timeout, page_size,
            symbols={str(symbol) for symbol in needed_symbols},
        ) if needed_symbols else []
        rows_by_symbol = {row["symbol"]: row for row in rows}
        for path, original in reports:
            report = copy.deepcopy(original)
            report_date = date.fromisoformat(report["date"])
            missing_prices: list[str] = []
            for entry in report["entries"]:
                row = None
                if market_id != "korea" and ("session_close" not in entry or "currency" not in entry):
                    symbol = entry["source_symbol"]
                    row = rows_by_symbol.get(symbol)
                if "session_close" not in entry:
                    if market_id == "korea":
                        entry["session_open"], entry["session_close"] = korean_session_prices(
                            entry, report_date, timeout,
                        )
                    else:
                        if row is None:
                            missing_prices.append(symbol)
                        else:
                            bar = matching_bar(row, report_date, max_offset, timezone_name)
                            entry["session_open"] = bar["open"]
                            entry["session_close"] = bar["close"]
                if "currency" not in entry:
                    if market_id == "korea":
                        entry["currency"] = "KRW"
                    elif row is not None and _text(row.get("currency")):
                        entry["currency"] = row["currency"].strip().upper()
                if entry.get("reason") == DEFAULT_REASON:
                    entry["reason"] = industry_reason(entry)
            metadata = report.setdefault("source_metadata", {})
            metadata["price_enrichment"] = {
                "status": "partial" if missing_prices else "complete",
                "provider": "Naver Finance dated daily history" if market_id == "korea"
                else "TradingView historical screener fields",
                "missing_symbols": sorted(missing_prices),
            }
            validate_report(report, path, reports_dir, markets)
            updated.append((path, report))

    # Validate every mutation before replacing any source report.
    for path, report in updated:
        atomic_json(path, report)
    return [path for path, _ in updated]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--market", action="append", help="Limit to a market; repeatable.")
    parser.add_argument("--start", type=date.fromisoformat)
    parser.add_argument("--end", type=date.fromisoformat)
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--page-size", type=int, default=500)
    parser.add_argument("--source-dir", type=Path, default=SOURCE_DIR)
    args = parser.parse_args()
    if args.start and args.end and args.end < args.start:
        parser.error("--end must not precede --start")
    try:
        paths = enrich_reports(
            args.source_dir, market_ids=set(args.market) if args.market else None,
            start=args.start, end=args.end, timeout=args.timeout, page_size=args.page_size,
        )
    except (TradingViewSourceError, ValueError) as exc:
        parser.exit(1, f"New-high report enrichment failed: {exc}\n")
    print(f"Enriched {len(paths)} daily new-high reports; unavailable symbols remain marked as unregistered prices.")


if __name__ == "__main__":
    main()
