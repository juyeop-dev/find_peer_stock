"""Collect one validated new-high report per market/session after the close."""

from __future__ import annotations

import argparse
import json
import os
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

from generate_new_high_data import SOURCE_DIR, load_markets, read_json, validate_report


RETRY_MINUTES = 30
# Collection windows are deliberately later than the regular closing auctions.
# IANA timezones handle the US/European daylight-saving changes.
COLLECTION_WINDOWS = {
    "korea": ("16:30", "08:30"),
    "taiwan": ("14:30", "08:30"),
    "japan": ("16:30", "08:30"),
    "china": ("16:00", "08:30"),
    "us": ("17:00", "09:00"),
    "europe": ("19:00", "08:30"),
}


def previous_success(previous: dict) -> dict[str, str]:
    """Keep only useful success history when moving to a new target state."""
    return {
        field: value
        for field in ("last_success_at", "last_success_date")
        if isinstance((value := previous.get(field)), str) and value
    }


def collection_date(market: dict, now: datetime) -> date | None:
    """Never snapshot a session in progress; allow catch-up before next open.

    Weekdays are only candidate dates. The provider must independently verify
    the trading date, so exchange holidays cannot become empty reports.
    """
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must include a timezone")
    after, before = COLLECTION_WINDOWS[market["id"]]
    after = market.get("refresh_after", after)
    local = now.astimezone(ZoneInfo(market["timezone"]))
    if local.weekday() < 5 and local.time() >= time.fromisoformat(after):
        return local.date()
    if local.weekday() < 5 and local.time() >= time.fromisoformat(before):
        return None
    candidate = local.date() - timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate -= timedelta(days=1)
    return candidate


def atomic_json(path: Path, payload: dict) -> None:
    """A failed fetch/validation must leave the last complete file intact."""
    text = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        temporary.write_text(text, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def refresh_new_highs(source_dir: Path = SOURCE_DIR, *, now: datetime | None = None,
                      fetch_report: Callable | None = None,
                      market_ids: set[str] | None = None) -> dict:
    from new_high_sources.tradingview import (
        SUPPORTED_MARKETS, TradingViewSourceError, TradingViewSourceNotReady,
        fetch_report as source_fetch,
    )

    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must include a timezone")
    fetch_report = fetch_report or source_fetch
    markets = {market["id"]: market for market in load_markets(source_dir)}
    if market_ids and not market_ids <= markets.keys():
        raise ValueError("Unknown market in --market")
    state_path = source_dir / "refresh-status.json"
    state = read_json(state_path) if state_path.exists() else {"schema_version": 1, "markets": {}}
    if not isinstance(state.get("markets"), dict):
        raise ValueError("refresh-status.json: markets must be an object")
    for market_id, market in markets.items():
        if market_ids and market_id not in market_ids:
            continue
        previous = state["markets"].get(market_id, {})
        if not isinstance(previous, dict):
            raise ValueError("refresh-status.json: each market status must be an object")
        if market_id not in SUPPORTED_MARKETS or market_id not in COLLECTION_WINDOWS:
            state["markets"][market_id] = {
                "status": "unsupported",
                "message": "자동 수집을 지원하는 자료원을 준비 중입니다.",
            }
            atomic_json(state_path, state)
            continue
        target = collection_date(market, now)
        if target is None:
            state["markets"][market_id] = {
                **previous_success(previous),
                "status": "pending",
                "target_date": now.astimezone(ZoneInfo(market["timezone"])).date().isoformat(),
                "message": "장 마감 후 일별 자료를 확인합니다.",
            }
            atomic_json(state_path, state)
            continue
        target_date = target.isoformat()
        reports_dir = source_dir / "reports"
        path = reports_dir / market_id / f"{target_date}.json"
        if path.exists():
            report = read_json(path)
            validate_report(report, path, reports_dir, markets)
            status = {
                "status": "updated",
                "target_date": target_date,
                "last_success_date": target_date,
                "message": "이 거래일의 신고가 자료가 등록되었습니다.",
            }
            if isinstance(report.get("collected_at"), str):
                status["last_success_at"] = report["collected_at"]
            state["markets"][market_id] = status
            atomic_json(state_path, state)
            continue
        retry_at = previous.get("next_retry_at")
        if previous.get("target_date") == target_date and retry_at:
            retry = datetime.fromisoformat(retry_at)
            if retry.tzinfo is None:
                raise ValueError("next_retry_at must include a timezone")
            if now < retry:
                retry_status = "error" if previous.get("status") == "error" else "pending"
                status = {
                    **previous_success(previous),
                    "status": retry_status,
                    "target_date": target_date,
                    "next_retry_at": retry_at,
                    "message": (
                        "수집 또는 검증에 실패해 기존 기록을 보존했습니다."
                        if retry_status == "error"
                        else "해당 거래일 자료 확인 대기 중입니다."
                    ),
                }
                if isinstance(previous.get("last_attempt_at"), str) and previous["last_attempt_at"]:
                    status["last_attempt_at"] = previous["last_attempt_at"]
                state["markets"][market_id] = status
                atomic_json(state_path, state)
                continue
        last_attempt_at = now.isoformat()
        try:
            report = fetch_report(market_id, target)
            if not isinstance(report, dict) or type(report.get("schema_version")) is not int or report["schema_version"] != 1:
                raise ValueError("Source report must have schema_version 1")
            if report.get("market") != market_id or report.get("date") != target_date:
                raise ValueError("Source report does not match the requested market/session")
            validate_report(report, path, reports_dir, markets)
            report["collected_at"] = now.isoformat()
            atomic_json(path, report)
        except (TradingViewSourceError, OSError, ValueError) as exc:
            status = {
                **previous_success(previous),
                "status": "pending" if isinstance(exc, TradingViewSourceNotReady) else "error",
                "target_date": target_date,
                "last_attempt_at": last_attempt_at,
                "next_retry_at": (now + timedelta(minutes=RETRY_MINUTES)).isoformat(),
                "message": (
                    "해당 거래일 자료 확인 대기 중입니다."
                    if isinstance(exc, TradingViewSourceNotReady)
                    else "수집 또는 검증에 실패해 기존 기록을 보존했습니다."
                ),
            }
            # Safe diagnostics belong in runner logs, not in the public UI.
            print(f"{market_id} {target_date}: {type(exc).__name__}: {exc}")
        else:
            status = {
                "status": "updated",
                "target_date": target_date,
                "last_attempt_at": last_attempt_at,
                "last_success_at": now.isoformat(),
                "last_success_date": target_date,
                "message": "장 마감 후 신고가 자료를 갱신했습니다.",
            }
        state["markets"][market_id] = status
        # Persist each market independently so later failures cannot erase it.
        atomic_json(state_path, state)
    atomic_json(state_path, state)
    return state


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=SOURCE_DIR)
    parser.add_argument("--market", action="append", help="Limit collection to a configured market; repeatable.")
    args = parser.parse_args()
    state = refresh_new_highs(args.source_dir, market_ids=set(args.market) if args.market else None)
    for market_id, status in state["markets"].items():
        print(f"{market_id}: {status['status']} ({status.get('target_date', '-')})")
    return int(any(status["status"] == "error" for market_id, status in state["markets"].items()
                   if not args.market or market_id in args.market))


if __name__ == "__main__":
    raise SystemExit(main())
