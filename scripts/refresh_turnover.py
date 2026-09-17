"""Collect one daily turnover top-30 report per market after the close."""

from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable

from generate_turnover_data import SOURCE_DIR, load_markets, read_json, validate_report
from refresh_new_highs import atomic_json, collection_date, previous_success


def refresh_turnover(source_dir: Path = SOURCE_DIR, *, now: datetime | None = None,
                     fetch_report: Callable | None = None, market_ids: set[str] | None = None,
                     target_date: date | None = None, force: bool = False) -> dict:
    from turnover_sources.tradingview import (
        SUPPORTED_MARKETS, TurnoverSourceError, TurnoverSourceNotReady, fetch_report as source_fetch,
    )

    now = now or datetime.now(timezone.utc)
    fetch_report = fetch_report or source_fetch
    markets = {market["id"]: market for market in load_markets(source_dir)}
    if market_ids and not market_ids <= markets.keys():
        raise ValueError("Unknown market in --market")
    state_path = source_dir / "refresh-status.json"
    state = read_json(state_path) if state_path.exists() else {"schema_version": 1, "markets": {}}
    for market_id, market in markets.items():
        if market_ids and market_id not in market_ids:
            continue
        previous = state["markets"].get(market_id, {})
        if market_id not in SUPPORTED_MARKETS:
            state["markets"][market_id] = {"status": "unsupported", "message": "자동 거래대금 수집 미지원 시장입니다.", **previous_success(previous)}
            continue
        target = target_date or collection_date(market, now)
        if target is None:
            state["markets"][market_id] = {"status": "pending", "message": "장 마감 후 수집합니다.", **previous_success(previous)}
            continue
        path = source_dir / "reports" / market_id / f"{target.isoformat()}.json"
        if path.exists() and not force:
            state["markets"][market_id] = {"status": "updated", "target_date": target.isoformat(), **previous_success(previous)}
            continue
        try:
            report = fetch_report(market_id, target)
            validate_report(report, path, source_dir / "reports", markets)
            atomic_json(path, report)
        except TurnoverSourceNotReady as exc:
            state["markets"][market_id] = {"status": "pending", "target_date": target.isoformat(), "message": str(exc), **previous_success(previous)}
        except (TurnoverSourceError, ValueError) as exc:
            state["markets"][market_id] = {"status": "error", "target_date": target.isoformat(), "message": str(exc), **previous_success(previous)}
        else:
            state["markets"][market_id] = {
                "status": "updated", "target_date": target.isoformat(),
                "last_success_date": target.isoformat(), "last_success_at": now.isoformat(),
            }
    atomic_json(state_path, state)
    return state


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=SOURCE_DIR)
    parser.add_argument("--market", action="append")
    parser.add_argument("--date", type=date.fromisoformat, help="Collect a specific latest source session (YYYY-MM-DD).")
    parser.add_argument("--force", action="store_true", help="Replace an existing report after validating a fresh snapshot.")
    args = parser.parse_args()
    state = refresh_turnover(args.source_dir, market_ids=set(args.market) if args.market else None,
                             target_date=args.date, force=args.force)
    print("Turnover refresh:", ", ".join(f"{key}={value['status']}" for key, value in state["markets"].items()))


if __name__ == "__main__":
    main()
