"""Recover missing European new-high reports from same-exchange public charts.

Daily and complete monthly series use split-adjusted regular sessions. Only
new-high reports are written; mixed-currency turnover rankings are not rebuilt.
Install scripts/requirements-chart-history.txt before live collection.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from backfill_yahoo_calendars import Bar, published_exchange, _company_name_matches
from generate_new_high_data import SOURCE_DIR, load_markets, validate_report
from new_high_sources.tradingview import _CONFIG, _DEFINITION_URL, _scan
from quote_sources.tradingview_chart import ChartHistoryError, ChartInstrumentError, fetch_chart
from refresh_new_highs import atomic_json, collection_date

CACHE_DIR = SOURCE_DIR.parent / "tmp_tradingview_chart"


def stamp_date(stamp: float, zone: str) -> date:
    return (datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=stamp)).astimezone(ZoneInfo(zone)).date()


def chart_bars(payload: dict, row: dict) -> list[Bar]:
    info = payload["info"]
    if payload["symbol"] != row["symbol"] or info["pro_name"] != row["symbol"] or info["source_id"] != row["exchange"]:
        raise ChartHistoryError(f"{row['symbol']}: chart identity or exchange mismatch")
    if info.get("type") in {"index", "forex", "crypto", "futures", "bond", "economic"}:
        raise ChartInstrumentError(row["symbol"], info)
    if row.get("description") and not _company_name_matches(row["description"], {"longName": info["description"]}):
        raise ChartHistoryError(f"{row['symbol']}: chart company name differs from scanner")
    if info["currency_code"].upper() != row["currency"].upper():
        raise ChartHistoryError(f"{row['symbol']}: chart and scanner currencies differ")
    zone = info["timezone"] or _CONFIG["europe"][1][row["exchange"]]
    bars = [Bar(stamp_date(point["timestamp"], zone), point["open"], point["high"], point["low"],
                point["close"], point["volume"]) for point in payload["bars"]]
    if len({bar.day for bar in bars}) != len(bars):
        raise ChartHistoryError(f"{row['symbol']}: duplicate chart session date")
    return bars


def completed_through(now: datetime) -> date:
    market = {"id": "europe", "timezone": "Europe/Paris", "refresh_after": "19:00"}
    completed = collection_date(market, now)
    if completed is not None:
        return completed
    previous = now.astimezone(ZoneInfo("Europe/Paris")).date() - timedelta(days=1)
    while previous.weekday() >= 5:
        previous -= timedelta(days=1)
    return previous


def cached_chart(row: dict, interval: str, count: int, *, cache_dir: Path, timeout: float,
                 required_end: date | None = None) -> dict:
    digest = hashlib.sha256(f"{row['symbol']}:{interval}:{count}".encode()).hexdigest()
    path = cache_dir / interval / f"{digest}.json"
    if path.exists():
        payload = json.loads(path.read_text(encoding="utf-8"))
        chart_bars(payload, row)
        fetched = datetime.fromisoformat(payload["fetched_at"])
        if required_end is None or completed_through(fetched) >= required_end:
            return payload
    last_error = None
    for attempt in range(3):
        try:
            payload = fetch_chart(row["symbol"], interval, count, timeout=timeout)
            chart_bars(payload, row)
            payload["fetched_at"] = datetime.now(timezone.utc).isoformat()
            atomic_json(path, payload)
            return payload
        except ChartHistoryError as exc:
            last_error = exc
            if isinstance(exc, ChartInstrumentError) or any(term in str(exc).lower() for term in ("permission", "unauthorized", "forbidden", "rate limit")):
                raise
            if attempt < 2:
                time.sleep(1 + attempt)
    raise last_error


def candidates(bars: list[Bar], sessions: set[date]) -> dict[date, dict]:
    result = {}
    for index, bar in enumerate(bars):
        if bar.day not in sessions or bar.volume <= 0:
            continue
        previous = bars[index - 1] if index else None
        lookback = bar.day - timedelta(weeks=52)
        prior_peak = max((item.high for item in bars if lookback <= item.day < bar.day), default=None)
        peak = max(bar.high, prior_peak or 0)
        if bar.high < peak * (1 - 1e-10):
            continue
        if bar.close < bar.open or previous is not None and bar.close < previous.close:
            continue
        result[bar.day] = {"bar": bar, "peak": peak, "prior_peak": prior_peak, "previous": previous}
    return result


def classify_high(bars: list[Bar], months: list[Bar], session: date, start: date) -> tuple[str, float]:
    if not months:
        raise ChartHistoryError("Missing complete monthly history")
    # A monthly high after the requested day must never be used to classify it.
    prior = max((bar.high for bar in months if bar.day < start.replace(day=1)), default=0)
    current = max((bar.high for bar in bars if start.replace(day=1) <= bar.day <= session), default=0)
    level = max(prior, current)
    day_bar = next(bar for bar in bars if bar.day == session)
    return ("all_time" if day_bar.high >= level * (1 - 1e-10) else "52_week"), level


def validate_session_coverage(session: date, counts: dict[str, int], eligible: list[dict], closed: set[str]) -> None:
    for exchange in _CONFIG["europe"][1]:
        expected = sum(row["exchange"] == exchange for row in eligible)
        if exchange not in closed and counts.get(exchange, 0) < expected * 0.5:
            raise ChartHistoryError(f"{session}: incomplete {exchange} session coverage ({counts.get(exchange, 0)}/{expected})")


def verify_series_end(row: dict, bars: list[Bar], requested_end: date) -> None:
    zone = _CONFIG["europe"][1][row["exchange"]]
    current = stamp_date(row["time"], zone)
    if bars[-1].day >= requested_end or current <= bars[-1].day:
        return
    previous = row.get("time[1]")
    # A thinly traded listing may have its first new quote today after weeks
    # without bars. The scanner's previous dated bar proves that gap; the live
    # incomplete bar is not needed for a requested range ending before today.
    if type(previous) in (int, float) and current > requested_end and stamp_date(previous, zone) == bars[-1].day:
        return
    raise ChartHistoryError(f"{row['symbol']}: chart ends before scanner's observed bar")


def build_reports(sessions: list[date], *, workers: int = 4, timeout: float = 30,
                  cache_dir: Path = CACHE_DIR, daily_bars: int = 400,
                  partial_history: bool = False) -> dict[date, dict]:
    if not sessions:
        return {}
    rows = _scan("europe", timeout, 5000)
    earliest, latest = min(sessions), max(sessions)
    eligible, excluded = [], []
    for row in rows:
        stamp = row.get("time")
        if stamp is None and all(row.get(field) is None for field in ("high", "volume", "price_52_week_high", "High.All")):
            excluded.append({"symbol": row["symbol"], "reason": "scanner has no observed price history"})
        elif type(stamp) in (float, int) and stamp_date(stamp, _CONFIG["europe"][1][row["exchange"]]) < earliest:
            excluded.append({"symbol": row["symbol"], "reason": "latest scanner bar predates requested range"})
        else:
            eligible.append(row)
    atomic_json(cache_dir / "universe.json", {"fetched_at": datetime.now(timezone.utc).isoformat(),
                                             "rows": rows, "excluded": excluded})
    print(f"europe: {len(rows)} scanned, {len(eligible)} histories required, {len(excluded)} pre-range/no-history symbols", flush=True)
    histories, failures, non_stock = {}, {}, []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(cached_chart, row, "1D", daily_bars, cache_dir=cache_dir, timeout=timeout,
                               required_end=latest): row for row in eligible}
        for completed, future in enumerate(as_completed(futures), start=1):
            row = futures[future]
            try:
                payload = future.result()
                bars = chart_bars(payload, row)
                if not bars:
                    raise ChartHistoryError(f"{row['symbol']}: scanner has prices but chart has no bars")
                if len(bars) == daily_bars and bars[0].day > earliest - timedelta(weeks=52):
                    raise ChartHistoryError(f"{row['symbol']}: truncated 52-week lookback")
                verify_series_end(row, bars, latest)
                histories[row["symbol"]] = (row, bars, payload)
            except ChartInstrumentError as exc:
                non_stock.append(exc.proof)
            except ChartHistoryError as exc:
                failures[row["symbol"]] = str(exc)
            if completed % 100 == 0 or completed == len(futures):
                atomic_json(cache_dir / "daily-failures.json", failures)
                print(f"europe: daily {completed}/{len(futures)}, verified={len(histories)}, unresolved={len(failures)}", flush=True)
    atomic_json(cache_dir / "daily-failures.json", failures)
    if failures:
        raise ChartHistoryError(f"{len(failures)} European histories unresolved; see {cache_dir / 'daily-failures.json'}")
    eligible = [row for row in eligible if row["symbol"] in histories]
    atomic_json(cache_dir / "non-stock-exclusions.json", non_stock)
    evidence = {symbol: candidates(bars, set(sessions)) for symbol, (_, bars, _) in histories.items()}
    candidate_symbols = [symbol for symbol, days in evidence.items() if days]
    print(f"europe: complete monthly histories required for {len(candidate_symbols)} candidates", flush=True)
    monthly, monthly_info = {}, {}
    failures = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(cached_chart, histories[symbol][0], "1M", 1500, cache_dir=cache_dir, timeout=timeout,
                               required_end=earliest.replace(day=1) - timedelta(days=1)): symbol
                   for symbol in candidate_symbols}
        for completed, future in enumerate(as_completed(futures), start=1):
            symbol = futures[future]
            try:
                payload = future.result()
                if len(payload["bars"]) >= 1500:
                    raise ChartHistoryError(f"{symbol}: monthly series may be truncated")
                monthly[symbol] = chart_bars(payload, histories[symbol][0])
                monthly_info[symbol] = payload["info"]
                if not monthly[symbol]:
                    raise ChartHistoryError(f"{symbol}: monthly series has no bars")
            except ChartHistoryError as exc:
                failures[symbol] = str(exc)
            if completed % 100 == 0 or completed == len(futures):
                atomic_json(cache_dir / "monthly-failures.json", failures)
                print(f"europe: monthly {completed}/{len(futures)}, unresolved={len(failures)}", flush=True)
    atomic_json(cache_dir / "monthly-failures.json", failures)
    if failures:
        raise ChartHistoryError(f"{len(failures)} European monthly histories unresolved; see {cache_dir / 'monthly-failures.json'}")
    reports = {}
    collected_at = datetime.now(timezone.utc).isoformat()
    gap_proofs = [{"symbol": symbol, "chart_last_session": str(bars[-1].day),
                   "previous_scanner_session": str(stamp_date(row["time[1]"], _CONFIG["europe"][1][row["exchange"]])),
                   "next_observed_session": str(stamp_date(row["time"], _CONFIG["europe"][1][row["exchange"]]))}
                  for symbol, (row, bars, _) in histories.items()
                  if bars[-1].day < latest and row.get("time[1]") is not None
                  and stamp_date(row["time"], _CONFIG["europe"][1][row["exchange"]]) > bars[-1].day]
    closure_path = SOURCE_DIR / "europe-exchange-closures.json"
    closure_rows = json.loads(closure_path.read_text(encoding="utf-8"))["closures"] if closure_path.exists() else []
    for session in sessions:
        members = {symbol: row for symbol, (row, bars, _) in histories.items() if any(bar.day == session for bar in bars)}
        by_exchange = {exchange: sum(row["exchange"] == exchange for row in members.values()) for exchange in _CONFIG["europe"][1]}
        scheduled_closed = {item["exchange"] for item in closure_rows if item["date"] == str(session)}
        coverage_warning = None
        try:
            validate_session_coverage(session, by_exchange, eligible, scheduled_closed)
        except ChartHistoryError as exc:
            if not partial_history:
                raise
            coverage_warning = str(exc)
        entries = []
        for symbol in candidate_symbols:
            check = evidence[symbol].get(session)
            if not check:
                continue
            row, bars, payload = histories[symbol]
            if row["exchange"] in scheduled_closed:
                continue
            bar, previous = check["bar"], check["previous"]
            high_type, all_time_level = classify_high(bars, monthly[symbol], session, earliest)
            sector, industry = row.get("sector") or "미분류", row.get("industry") or "업종 정보 미확인"
            entries.append({
                "ticker": symbol, "source_symbol": symbol, "name": row["description"],
                "exchange": published_exchange(row["exchange"]), "category": sector, "high_type": high_type,
                "reason": f"업종: {sector} · {industry}", "description": f"{row['description']} · {industry}",
                "session_open": bar.open, "session_close": bar.close, "session_volume": bar.volume,
                "change_pct": (bar.close / previous.close - 1) * 100 if previous else None,
                "currency": payload["info"]["currency_code"].upper(),
                "high_verification": {"source": "TradingView split-adjusted regular-session daily/monthly charts",
                    "source_url": f"https://www.tradingview.com/symbols/{row['exchange']}-{row['name']}/",
                    "date": str(session), "daily_high": bar.high, "prior_52_week_high": check["prior_peak"],
                    "period_52_week_high": check["peak"],
                    "prior_all_time_or_current_month_high": all_time_level,
                    "previous_close": previous.close if previous else None, "passes_close_filter": True,
                    "instrument_type": monthly_info[symbol].get("type"),
                    "symbol_identity": payload["info"]["pro_name"], "chart_source_id": payload["info"]["source_id"]},
            })
        entries.sort(key=lambda entry: (entry["exchange"], entry["ticker"]))
        reports[session] = {"schema_version": 1, "market": "europe", "date": str(session),
            "summary": ("부분 복원: 당시 일봉을 제공하는 종목만 포함하며 시장 전체 신고가 수와 다를 수 있습니다. " + " · ".join(f"{exchange} {by_exchange[exchange]}/{sum(row['exchange'] == exchange for row in eligible)}종목 확인" for exchange in by_exchange) + ". " if partial_history else "") + "TradingView 동일 거래소의 분할 조정 일봉·전체 월봉으로 복원했습니다. 거래량이 있는 신고가 종목 중 음봉 또는 전일 대비 하락 마감 종목은 제외합니다.",
            "sources": [{"label": "TradingView historical charts", "url": "https://www.tradingview.com/chart/"},
                        {"label": "TradingView 신고가 산정 기준", "url": _DEFINITION_URL}],
            "entries": entries, "collected_at": collected_at,
            "source_metadata": {"provider": "TradingView public daily/monthly chart history",
                "universe_provider": "TradingView public scanner", "fetched_at": collected_at,
                "universe": "Current TradingView-listed stocks on EURONEXT, XETR, LSE, SIX; ETFs and delisted historical listings excluded",
                "scanned_symbols": len(rows), "history_symbols": len(histories),
                "history_required_symbols": len(eligible),
                "excluded_pre_range_or_no_history": len(excluded), "unresolved_symbols": 0,
                "non_stock_exclusions": non_stock,
                "session_symbols": len(members), "session_symbols_by_exchange": by_exchange,
                "scheduled_closed_exchanges": sorted(scheduled_closed),
                "scanner_confirmed_no_trade_gaps": gap_proofs,
                "coverage_ratio": len(members) / len(eligible), "coverage_status": "partial" if partial_history else "verified",
                "coverage_warning": coverage_warning, "pagination_complete": True, "split_adjusted": True,
                "session": "regular", "monthly_history_complete": True,
                "definition": "daily high >= 52-week/all-time high; volume > 0; close >= open and prior close; ties included"}}
    return reports


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", required=True, type=date.fromisoformat)
    parser.add_argument("--end", required=True, type=date.fromisoformat)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--daily-bars", type=int, default=400,
                        help="Daily history depth; increase for earlier backfills (maximum 5000).")
    parser.add_argument("--cache-dir", type=Path, default=CACHE_DIR)
    parser.add_argument("--partial-history", action="store_true", help="Publish explicitly labelled partial historical observations; never claim complete session coverage.")
    args = parser.parse_args()
    if args.end < args.start or not 1 <= args.workers <= 4 or not 1 <= args.daily_bars <= 5000:
        parser.error("Invalid date range, workers (1-4), or daily history depth (1-5000)")
    markets = {market["id"]: market for market in load_markets(SOURCE_DIR)}
    now = datetime.now(timezone.utc)
    end = min(args.end, completed_through(now))
    closures = json.loads((SOURCE_DIR.parent / f"market-closures/{args.start.year}.json").read_text(encoding="utf-8"))
    closed = next(set(item["dates"]) for item in closures["markets"] if item["market"] == "europe")
    sessions = [args.start + timedelta(days=offset) for offset in range((end - args.start).days + 1)
                if (args.start + timedelta(days=offset)).weekday() < 5
                and str(args.start + timedelta(days=offset)) not in closed
                and not (SOURCE_DIR / "reports/europe" / f"{args.start + timedelta(days=offset)}.json").exists()]
    print(f"europe: recovering {len(sessions)} missing completed sessions", flush=True)
    try:
        reports = build_reports(sessions, workers=args.workers, timeout=args.timeout,
                                cache_dir=args.cache_dir, daily_bars=args.daily_bars, partial_history=args.partial_history)
        for session, report in reports.items():
            validate_report(report, SOURCE_DIR / "reports/europe" / f"{session}.json", SOURCE_DIR / "reports", markets)
        for session, report in reports.items():
            path = SOURCE_DIR / "reports/europe" / f"{session}.json"
            if path.exists():
                print(f"europe {session}: concurrent report preserved", flush=True)
                continue
            atomic_json(path, report)
            print(f"europe {session}: {len(report['entries'])} verified entries", flush=True)
    except ChartHistoryError as exc:
        parser.exit(1, f"European history recovery failed: {exc}\n")


if __name__ == "__main__":
    main()
