"""Collect and publish completed Korean daily low-to-close rebound reports."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime, timezone
import json
import math
from pathlib import Path
import re
from zoneinfo import ZoneInfo

from archive_paths import monthly_report_path
from market_closures import load_scheduled_closures
from refresh_new_highs import atomic_json, collection_date, previous_success
from turnover_sources.tradingview import _request_json

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/rebounds"
PUBLIC = ROOT / "frontend/public/data/rebounds"
RULES = {"KOSPI": {"market_cap_min": 5_000_000_000_000, "rebound_min": 8},
         "KOSDAQ": {"market_cap_min": 1_000_000_000_000, "rebound_min": 5}}
COLUMNS = ("name", "description", "exchange", "type", "subtype", "close", "low", "change",
           "market_cap_basic", "currency", "time", "indexes", "sector", "industry")
KNOWN_MARKETS = {"korea", "us", "china", "taiwan", "japan", "europe"}


def number(value):
    return type(value) in (int, float) and math.isfinite(value)


def closures():
    return [row for row in load_scheduled_closures(ROOT / "data/market-closures", KNOWN_MARKETS) if row["market"] == "korea"]


def report_from_scan(payload, target: date, *, now=None, names=None):
    now = now or datetime.now(timezone.utc)
    rows = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or type(payload.get("totalCount")) is not int or not 1 <= payload["totalCount"] <= 6000 or len(rows) != payload["totalCount"]:
        raise ValueError("국내 전체 종목 조회가 완결되지 않았습니다.")
    entries, seen, latest, excluded = [], set(), {}, Counter()
    for item in rows:
        if not isinstance(item, dict) or not isinstance(item.get("d"), list) or len(item["d"]) != len(COLUMNS):
            raise ValueError("반등 원자료의 열 구성이 일치하지 않습니다.")
        row = dict(zip(COLUMNS, item["d"]))
        symbol = item.get("s")
        if not isinstance(symbol, str) or symbol in seen:
            raise ValueError("종목 코드가 없거나 중복되었습니다.")
        seen.add(symbol)
        if row["exchange"] != "KRX" or row["type"] != "stock" or row["subtype"] != "common" or not re.fullmatch(r"[0-9A-Z]{6}", row["name"] or "") or symbol != f"KRX:{row['name']}":
            excluded["unsupported_listing"] += 1
            continue
        indexes = row["indexes"] if row["indexes"] is not None else []
        if not isinstance(indexes, list) or any(not isinstance(index, dict) for index in indexes):
            raise ValueError(f"{symbol}: 시장 구분을 확인할 수 없습니다.")
        boards = [board for board in RULES if any(index.get("proname") == f"KRX:{board}" for index in indexes)]
        if len(boards) > 1:
            raise ValueError(f"{symbol}: 시장 구분이 충돌합니다.")
        if not boards:
            excluded["unsupported_listing"] += 1
            continue
        board = boards[0]
        if row["currency"] != "KRW":
            raise ValueError(f"{symbol}: 원화 실적이 아닙니다.")
        if not number(row["time"]) or row["time"] <= 0:
            excluded["missing_session"] += 1
            continue
        day = datetime.fromtimestamp(row["time"], timezone.utc).astimezone(ZoneInfo("Asia/Seoul")).date()
        if day > now.astimezone(ZoneInfo("Asia/Seoul")).date():
            raise ValueError(f"{symbol}: 미래 거래일입니다.")
        latest[board] = max(day, latest.get(board, day))
        if day != target:
            excluded["stale_session"] += 1
            continue
        cap, change, close, low = (row[key] for key in ("market_cap_basic", "change", "close", "low"))
        if not number(cap) or cap <= 0:
            excluded["missing_market_cap"] += 1
            continue
        if cap < RULES[board]["market_cap_min"]:
            excluded["below_market_cap"] += 1
            continue
        if not number(change):
            excluded["missing_change"] += 1
            continue
        if change < 0:
            excluded["declining"] += 1
            continue
        if not number(close) or not number(low) or not 0 < low <= close:
            raise ValueError(f"{symbol}: 당일 저가 또는 종가가 유효하지 않습니다.")
        rebound = (close / low - 1) * 100
        # Never round before filtering; equality is inclusive at the threshold.
        if rebound + 1e-10 < RULES[board]["rebound_min"]:
            excluded["below_rebound"] += 1
            continue
        ticker = f"{row['name']}.{ 'KS' if board == 'KOSPI' else 'KQ'}"
        name = (names or {}).get(ticker) or row["description"]
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"{symbol}: 종목명이 없습니다.")
        entries.append({"ticker": ticker, "name": name.removesuffix("보통주").strip(), "exchange": board,
                        "currency": "KRW", "price": close, "low": low, "change_pct": change,
                        "rebound_pct": rebound, "market_cap": cap, "market_cap_currency": "KRW",
                        "sector": row["sector"] or "미분류", "industry": row["industry"] or "미분류"})
    if any(latest.get(board) != target for board in RULES):
        raise ValueError("제공처의 두 시장 최신 거래일이 요청한 날짜와 일치하지 않습니다.")
    report = {"schema_version": 1, "market": "korea", "date": target.isoformat(), "rules": RULES,
              "entries": sorted(entries, key=lambda row: (list(RULES).index(row["exchange"]), -row["rebound_pct"], row["ticker"])),
              "source_metadata": {"provider": "TradingView public scanner", "fetched_at": now.isoformat(),
                  "session": "daily", "timezone": "Asia/Seoul", "scanned_symbols": len(rows),
                  "excluded": dict(excluded), "latest_session_by_board": {key: value.isoformat() for key, value in latest.items()}},
              "sources": [{"label": "TradingView 국내 주식 스크리너", "url": "https://kr.tradingview.com/markets/stocks-korea/market-movers-all-stocks/"}]}
    validate_report(report)
    return report


def validate_report(report):
    if not isinstance(report, dict) or report.get("schema_version") != 1 or report.get("market") != "korea" or report.get("rules") != RULES:
        raise ValueError("반등 보고서 형식 또는 선별 조건이 일치하지 않습니다.")
    day = date.fromisoformat(report["date"])
    if day.weekday() >= 5 or not isinstance(report.get("entries"), list):
        raise ValueError("거래일 또는 종목 목록이 유효하지 않습니다.")
    metadata = report.get("source_metadata", {})
    fetched = datetime.fromisoformat(metadata.get("fetched_at", ""))
    if fetched.tzinfo is None or metadata.get("session") != "daily" or metadata.get("latest_session_by_board") != {board: day.isoformat() for board in RULES}:
        raise ValueError("일봉 기준일 또는 수집 시각을 확인할 수 없습니다.")
    seen = set()
    for row in report["entries"]:
        board = row.get("exchange")
        suffix = "KS" if board == "KOSPI" else "KQ"
        if board not in RULES or row.get("currency") != "KRW" or row.get("market_cap_currency") != "KRW" or not re.fullmatch(rf"[0-9A-Z]{{6}}\.{suffix}", row.get("ticker", "")) or row["ticker"] in seen or not isinstance(row.get("name"), str) or not row["name"].strip():
            raise ValueError("종목명·시장·코드·통화가 유효하지 않거나 중복되었습니다.")
        seen.add(row["ticker"])
        if any(not number(row.get(key)) for key in ("price", "low", "market_cap", "change_pct", "rebound_pct")):
            raise ValueError("반등 계산에 필요한 수치가 없습니다.")
        if not 0 < row["low"] <= row["price"] or row["market_cap"] < RULES[board]["market_cap_min"] or row["change_pct"] < 0:
            raise ValueError("시가총액·등락률·당일 저가 조건이 일치하지 않습니다.")
        actual = (row["price"] / row["low"] - 1) * 100
        if actual + 1e-10 < RULES[board]["rebound_min"] or not math.isclose(actual, row["rebound_pct"], abs_tol=1e-8):
            raise ValueError("반등률 계산 또는 선별 조건이 일치하지 않습니다.")
    if report["entries"] != sorted(report["entries"], key=lambda row: (list(RULES).index(row["exchange"]), -row["rebound_pct"], row["ticker"])):
        raise ValueError("반등률 내림차순 정렬이 아닙니다.")


def collect(source_dir=SOURCE, *, now=None, target_date=None, fetcher=None, force=False):
    now = now or datetime.now(timezone.utc)
    local = now.astimezone(ZoneInfo("Asia/Seoul"))
    state_path = source_dir / "refresh-status.json"
    previous = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    state = {"schema_version": 1, "checked_at": now.isoformat(), **previous_success(previous)}
    target = target_date or collection_date({"id": "korea", "timezone": "Asia/Seoul", "refresh_after": "15:50"}, now)
    closed = {row["date"]: row["reason"] for row in closures()}
    if target is None or target > local.date() or target == local.date() and (local.hour, local.minute) < (15, 50):
        state.update(status="pending", message="장 마감 일봉은 제공처 지연을 고려해 15:50부터 수집합니다.")
    elif target.weekday() >= 5 or target.isoformat() in closed:
        state.update(status="closed", message=closed.get(target.isoformat(), "주말 휴장입니다."))
    else:
        state["target_date"] = target.isoformat()
        path = monthly_report_path(source_dir / "reports", "korea", target)
        try:
            if path.exists() and not force:
                validate_report(json.loads(path.read_text(encoding="utf-8")))
            else:
                payload = (fetcher or (lambda: _request_json("https://scanner.tradingview.com/korea/scan", {
                    "columns": list(COLUMNS), "filter": [{"left": "type", "operation": "equal", "right": "stock"}, {"left": "subtype", "operation": "equal", "right": "common"}],
                    "options": {"lang": "ko", "price_conversion": {"to_symbol": True}}, "range": [0, 6000]}, 30)))()
                names_path = ROOT / "data/seed/korean_company_names.json"
                names = json.loads(names_path.read_text(encoding="utf-8")).get("names", {}) if names_path.exists() else {}
                report = report_from_scan(payload, target, now=now, names=names)
                atomic_json(path, report)
            state.update(status="updated", message="마감 일봉 반등 종목을 저장했습니다.", last_success_date=target.isoformat(), last_success_at=now.isoformat())
        except (ValueError, OSError, OverflowError) as exc:
            state.update(status="error", message=str(exc))
    atomic_json(state_path, state)
    return state


def publish(source_dir=SOURCE, output_dir=PUBLIC):
    reports = []
    for path in sorted((source_dir / "reports/korea").glob("*/*.json")):
        report = json.loads(path.read_text(encoding="utf-8"))
        validate_report(report)
        if path != monthly_report_path(source_dir / "reports", "korea", report["date"]):
            raise ValueError(f"보고서 날짜와 경로가 일치하지 않습니다: {path}")
        reports.append(report)
    # Validate the entire archive before publishing any report.
    index = {"schema_version": 1, "market": "korea", "rules": RULES, "closures": closures(),
             "reports": [{"date": report["date"], "count": len(report["entries"]),
                          "counts": dict(Counter(row["exchange"] for row in report["entries"])),
                          "fetched_at": report["source_metadata"]["fetched_at"]} for report in reversed(reports)],
             "refresh": json.loads((source_dir / "refresh-status.json").read_text(encoding="utf-8")) if (source_dir / "refresh-status.json").exists() else {"status": "pending", "message": "첫 장 마감 수집을 기다리고 있습니다."}}
    for report in reports:
        atomic_json(monthly_report_path(output_dir, "korea", report["date"]), report)
    atomic_json(output_dir / "index.json", index)
    return index


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["collect", "publish"])
    parser.add_argument("--source-dir", type=Path, default=SOURCE)
    parser.add_argument("--output-dir", type=Path, default=PUBLIC)
    parser.add_argument("--date", type=date.fromisoformat)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    result = collect(args.source_dir, target_date=args.date, force=args.force) if args.action == "collect" else publish(args.source_dir, args.output_dir)
    print(f"Rebounds: {result['status']}" if args.action == "collect" else f"Published {len(result['reports'])} rebound sessions")
    if args.action == "collect" and result["status"] == "error":
        raise SystemExit(result["message"])


if __name__ == "__main__":
    main()
