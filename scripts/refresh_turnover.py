"""Collect one daily turnover top-30 report per market after the close."""

from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

from archive_paths import monthly_report_path
from generate_turnover_data import SOURCE_DIR, load_markets, read_json, validate_report
from market_closures import load_scheduled_closures
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
    scheduled = {(item["market"], item["date"]): item for item in
                 load_scheduled_closures(source_dir.parent / "market-closures", set(markets))}
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
        # 15:30 regular close, plus 20 minutes for delayed scanner data. Keep
        # new-high collection windows independent from turnover collection.
        collection_market = {**market, "refresh_after": "15:50"} if market_id == "korea" else market
        target = target_date or collection_date(collection_market, now)
        if market_id == "korea" and target_date is not None:
            local = now.astimezone(ZoneInfo("Asia/Seoul"))
            if target_date > local.date() or target_date == local.date() and (local.hour, local.minute) < (15, 50):
                state["markets"][market_id] = {"status": "pending", "target_date": target_date.isoformat(),
                    "message": "정규장 15:30 마감 자료는 제공처 지연을 고려해 15:50부터 수집합니다.", **previous_success(previous)}
                continue
        if target is None:
            local_day = now.astimezone(ZoneInfo(market["timezone"])).date().isoformat()
            closure = scheduled.get((market_id, local_day))
            state["markets"][market_id] = {
                "status": "closed" if closure else "pending", "target_date": local_day,
                "message": f"{closure['reason']} 휴장입니다." if closure else "장 마감 후 수집합니다.",
                **previous_success(previous),
            }
            continue
        path = monthly_report_path(source_dir / "reports", market_id, target)
        if path.exists() and not force:
            state["markets"][market_id] = {"status": "updated", "target_date": target.isoformat(), **previous_success(previous)}
            continue
        closure = scheduled.get((market_id, target.isoformat())) if target_date is None or market_id == "korea" else None
        if closure:
            state["markets"][market_id] = {
                "status": "closed", "target_date": target.isoformat(),
                "message": f"{closure['reason']} 휴장입니다.", **previous_success(previous),
            }
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
