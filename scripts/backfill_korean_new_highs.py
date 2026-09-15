"""Backfill Korean daily new-high reports from dated Naver OHLC history."""

from __future__ import annotations

import argparse
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode

from generate_new_high_data import SOURCE_DIR, load_markets, validate_report
from new_high_sources.tradingview import (
    TradingViewSourceError,
    _request_daily_history,
    _scan,
    fetch_korean_listing,
)
from refresh_new_highs import atomic_json


def requested_dates(start: date, end: date) -> list[date]:
    if end < start:
        raise ValueError("end date must not precede start date")
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)
            if (start + timedelta(days=offset)).weekday() < 5]


def history_url(code: str, start: date, end: date) -> str:
    return "https://api.finance.naver.com/siseJson.naver?" + urlencode({
        "symbol": code,
        "requestType": "1",
        "startTime": start.strftime("%Y%m%d"),
        "endTime": end.strftime("%Y%m%d"),
        "timeframe": "day",
    })


def parse_history(rows: list, *, code: str, start: date, end: date) -> dict[date, list]:
    parsed: dict[date, list] = {}
    for row in rows:
        if not isinstance(row, list) or len(row) < 6:
            raise TradingViewSourceError(f"KRX:{code}: malformed daily history")
        try:
            day = datetime.strptime(str(row[0]), "%Y%m%d").date()
        except ValueError as exc:
            raise TradingViewSourceError(f"KRX:{code}: invalid daily history date") from exc
        if day in parsed or not start <= day <= end:
            raise TradingViewSourceError(f"KRX:{code}: duplicate or unexpected daily history date")
        if any(type(row[index]) not in (int, float) for index in range(1, 6)):
            raise TradingViewSourceError(f"KRX:{code}: nonnumeric daily history")
        if row[2] < 0 or row[4] <= 0 or row[5] < 0:
            raise TradingViewSourceError(f"KRX:{code}: invalid high, close or volume")
        parsed[day] = row
    return parsed


def classify_window(history: dict[date, list], sessions: list[date]) -> dict[date, dict[str, Any]]:
    results: dict[date, dict[str, Any]] = {}
    ordered = sorted(history)
    for session in sessions:
        current = history.get(session)
        if current is None:
            continue
        if any(current[index] <= 0 for index in (1, 2, 3, 4)) or current[5] <= 0:
            continue
        previous_days = [day for day in ordered if day < session]
        if not previous_days:
            continue
        previous_day = previous_days[-1]
        previous_close = history[previous_day][4]
        lookback_start = session - timedelta(weeks=52)
        prior_highs = [history[day][2] for day in previous_days
                       if day >= lookback_start and history[day][2] > 0]
        if not prior_highs or current[2] < max(prior_highs):
            continue
        bearish_candle = current[4] < current[1]
        down_close = current[4] < previous_close
        results[session] = {
            "date": session.isoformat(),
            "open": current[1],
            "daily_high": current[2],
            "low": current[3],
            "close": current[4],
            "previous_close": previous_close,
            "volume": current[5],
            "prior_52_week_high": max(prior_highs),
            "observed_bars": sum(lookback_start <= day <= session for day in ordered),
            "first_observed_date": min(day for day in ordered if day >= lookback_start).isoformat(),
            "confirmed": True,
            "matches_prior_high": current[2] == max(prior_highs),
            "bearish_candle": bearish_candle,
            "down_close": down_close,
            "passes_close_filter": not bearish_candle and not down_close,
        }
    return results


def request_with_retry(url: str, timeout: float, attempts: int = 3) -> list:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            return _request_daily_history(url, timeout)
        except TradingViewSourceError as exc:
            if "missing daily history" in str(exc):
                return []
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(0.5 * (attempt + 1))
    raise TradingViewSourceError(f"Cannot complete historical backfill: {last_error}")


def parallel_map(items: list, worker: Callable, workers: int, label: str) -> list:
    results = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(worker, item): item for item in items}
        for completed, future in enumerate(as_completed(futures), start=1):
            results.append(future.result())
            if completed % 250 == 0 or completed == len(futures):
                print(f"{label}: {completed}/{len(futures)}")
    return results


def build_reports(start: date, end: date, *, timeout: float = 30,
                  workers: int = 24) -> tuple[dict[date, dict], dict[date, dict]]:
    sessions = requested_dates(start, end)
    if not sessions:
        raise ValueError("date range has no weekdays")
    universe = _scan("korea", timeout, 500)
    row_by_code = {row["name"]: row for row in universe}
    window_start = sessions[0] - timedelta(weeks=52)

    def fetch_window(row: dict) -> tuple[str, dict[date, list]]:
        code = row["name"]
        url = history_url(code, window_start, sessions[-1])
        raw = request_with_retry(url, timeout)
        return code, parse_history(raw, code=code, start=window_start, end=sessions[-1])

    histories = dict(parallel_map(universe, fetch_window, workers, "52-week histories"))
    session_coverage = {session: sum(session in history for history in histories.values()) for session in sessions}
    for session, count in session_coverage.items():
        if count < 1000:
            raise TradingViewSourceError(f"{session}: incomplete Korean session coverage ({count} symbols)")

    candidates: dict[date, list[tuple[str, dict[str, Any]]]] = {session: [] for session in sessions}
    for code, history in histories.items():
        for session, evidence in classify_window(history, sessions).items():
            candidates[session].append((code, evidence))
    candidate_codes = sorted({code for rows in candidates.values() for code, _ in rows})

    def fetch_details(code: str) -> tuple[str, dict[date, list], dict[str, str]]:
        url = history_url(code, date(1980, 1, 1), sessions[-1])
        raw = request_with_retry(url, timeout)
        history = parse_history(raw, code=code, start=date(1980, 1, 1), end=sessions[-1])
        return code, history, fetch_korean_listing(code, timeout)

    details = {code: (history, listing) for code, history, listing in
               parallel_map(candidate_codes, fetch_details, workers, "candidate histories")}
    collected_at = datetime.now(timezone.utc).isoformat()
    reports: dict[date, dict] = {}
    reviews: dict[date, dict] = {}
    for session in sessions:
        entries = []
        checks = []
        for code, evidence in sorted(candidates[session]):
            full_history, listing = details[code]
            prior_all_time = max((row[2] for day, row in full_history.items()
                                  if day < session and row[2] > 0), default=None)
            high_type = "all_time" if prior_all_time is None or evidence["daily_high"] >= prior_all_time else "52_week"
            check = {"ticker": code, **evidence, "prior_all_time_high": prior_all_time,
                     "high_type": high_type, "included": evidence["passes_close_filter"]}
            checks.append(check)
            if not evidence["passes_close_filter"]:
                continue
            source_row = row_by_code[code]
            exchange = listing["exchange"]
            suffix = ".KS" if exchange == "KOSPI" else ".KQ"
            name = listing["name"]
            sector = source_row["sector"].strip() if isinstance(source_row["sector"], str) and source_row["sector"].strip() else "미분류"
            industry = source_row["industry"].strip() if isinstance(source_row["industry"], str) and source_row["industry"].strip() else "업종 정보 미확인"
            change_pct = (evidence["close"] - evidence["previous_close"]) / evidence["previous_close"] * 100
            entries.append({
                "ticker": code + suffix, "name": name, "exchange": exchange,
                "category": sector, "high_type": high_type, "reason": f"업종: {sector} · {industry}",
                "description": f"{name} · {industry}", "change_pct": change_pct,
                "session_open": evidence["open"], "session_close": evidence["close"],
                "currency": "KRW",
                "source_symbol": source_row["symbol"], "name_original": source_row["description"],
                "name_source_url": listing["source_url"],
                "high_verification": {
                    "source": "Naver Finance adjusted daily history",
                    "source_url": history_url(code, session - timedelta(weeks=52), session),
                    **evidence,
                },
            })
        entries.sort(key=lambda entry: (entry["exchange"], entry["ticker"]))
        reports[session] = {
            "schema_version": 1, "market": "korea", "date": session.isoformat(),
            "summary": "과거 일봉 전체 대조 기준. 당일 장중 고가가 52주·전체기간 고가에 도달하고, 음봉 또는 전일 대비 하락 마감이 아닌 종목입니다. 전체기간 신고가를 우선 표시하며 신고가 배경은 별도 확인 전입니다.",
            "sources": [
                {"label": "Naver Finance 조정 일봉·한국 종목명", "url": "https://stock.naver.com/"},
                {"label": "TradingView 한국 주식 종목군·업종", "url": "https://www.tradingview.com/screener/"},
            ],
            "entries": entries,
            "source_metadata": {
                "provider": "Naver Finance adjusted daily history",
                "universe_provider": "TradingView public scanner",
                "fetched_at": collected_at,
                "definition": "daily high >= prior 52-week high; close >= open; close >= previous close; all-time takes precedence; ties included",
                "scanned_symbols": len(universe), "session_symbols": session_coverage[session],
                "raw_new_high_candidates": len(candidates[session]),
                "excluded_bearish_or_down_close": sum(not evidence["passes_close_filter"] for _, evidence in candidates[session]),
                "pagination_complete": True,
            },
            "collected_at": collected_at,
        }
        reviews[session] = {
            "schema_version": 1, "market": "korea", "date": session.isoformat(),
            "reviewed_at": collected_at, "scanned_symbols": len(universe),
            "session_symbols": session_coverage[session], "checks": checks,
        }
    return reports, reviews


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", required=True, type=date.fromisoformat)
    parser.add_argument("--end", required=True, type=date.fromisoformat)
    parser.add_argument("--workers", type=int, default=24)
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--source-dir", type=Path, default=SOURCE_DIR)
    args = parser.parse_args()
    if not 1 <= args.workers <= 64:
        parser.error("--workers must be between 1 and 64")
    reports, reviews = build_reports(args.start, args.end, timeout=args.timeout, workers=args.workers)
    markets = {market["id"]: market for market in load_markets(args.source_dir)}
    for session, report in reports.items():
        report_path = args.source_dir / "reports" / "korea" / f"{session}.json"
        if report_path.exists() and not args.force:
            parser.error(f"report already exists: {report_path}; use --force to replace it")
        validate_report(report, report_path, args.source_dir / "reports", markets)
    for session, report in reports.items():
        atomic_json(args.source_dir / "reports" / "korea" / f"{session}.json", report)
        atomic_json(args.source_dir / "reviews" / "korea" / f"{session}.json", reviews[session])
        print(f"korea {session}: {len(report['entries'])} entries")


if __name__ == "__main__":
    main()
