"""Restore daily rebounds from checksum-verified, dated KRX OHLC/capitalization.

Only this explicit backfill needs pyarrow; normal collection/publishing does not.
Use revision-pinned FinanceData/marcap annual Parquet files accompanied by the
existing .source.json metadata. Historical rows include delisted stocks.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
from zoneinfo import ZoneInfo

from rebound_data import ROOT, SOURCE, RULES, closures, number, validate_report
from archive_paths import monthly_report_path
from recalculate_korea_history import normalize_row, SOURCE as PROVIDER, SOURCE_URL
from refresh_new_highs import atomic_json

COLUMNS = ["Date", "Code", "Name", "Close", "Low", "ChangesRatio", "Volume", "Amount", "Marcap", "Stocks", "Market"]
NOTE = "KRX 당시 상장 종목의 당일 저가·종가·시가총액으로 복원한 기록입니다. 현재 시총이나 분할 조정 가격을 소급 적용하지 않습니다."


def report_from_rows(rows, day, info, *, now=None, minimum_symbols=1500):
    entries, excluded, seen, boards = [], Counter(), set(), Counter()
    for raw in rows:
        if raw["Date"].date() != day:
            raise ValueError(f"{day}: 원본 거래일이 일치하지 않습니다.")
        code = raw.get("Code")
        if not isinstance(code, str) or not re.fullmatch(r"[0-9A-Z]{6}", code) or code in seen:
            raise ValueError(f"{day}: 종목 코드가 잘못되었거나 중복되었습니다.")
        seen.add(code)
        # KRX common shares have a final share-class digit of 0. Do not use
        # today's scanner membership: that would drop historical delistings.
        market = raw["Market"]
        board = "KOSDAQ" if market.startswith("KOSDAQ") else market
        if board not in RULES or not code.endswith("0"):
            excluded["unsupported_listing"] += 1
            continue
        row = normalize_row(raw)
        if row is None:
            excluded["inactive_listing"] += 1
            continue
        boards[board] += 1
        if row["volume"] == 0:
            excluded["no_trading"] += 1
            continue
        if row["market_cap"] < RULES[board]["market_cap_min"]:
            excluded["below_market_cap"] += 1
            continue
        if row["change_pct"] < 0:
            excluded["declining"] += 1
            continue
        low = raw.get("Low")
        if not number(low) or not 0 < low <= row["price"]:
            raise ValueError(f"{day}/{code}: 당일 저가를 확인할 수 없습니다.")
        rebound = (row["price"] / low - 1) * 100
        if rebound + 1e-10 < RULES[board]["rebound_min"]:
            excluded["below_rebound"] += 1
            continue
        entries.append({"ticker": code + (".KS" if board == "KOSPI" else ".KQ"),
                        "name": row["name"], "exchange": board, "currency": "KRW",
                        "price": row["price"], "low": low, "change_pct": row["change_pct"],
                        "rebound_pct": rebound, "market_cap": row["market_cap"],
                        "market_cap_currency": "KRW", "market_cap_date": str(day),
                        "sector": "미분류", "industry": "미분류"})
    if sum(boards.values()) < minimum_symbols or any(not boards[board] for board in RULES):
        raise ValueError(f"{day}: 국내 전체 종목 원본이 불완전합니다: {dict(boards)}")
    report = {"schema_version": 1, "market": "korea", "date": str(day), "rules": RULES,
              "entries": sorted(entries, key=lambda row: (list(RULES).index(row["exchange"]), -row["rebound_pct"], row["ticker"])),
              "source_metadata": {"provider": PROVIDER, "fetched_at": info["fetched_at"],
                  "reconstructed_at": (now or datetime.now(timezone.utc)).isoformat(),
                  "session": "daily", "timezone": "Asia/Seoul", "scanned_symbols": len(seen),
                  "common_symbols_by_board": dict(boards), "excluded": dict(excluded),
                  "latest_session_by_board": {board: str(day) for board in RULES},
                  "source_revision": info["revision"], "source_sha256": info["sha256"],
                  "price_basis": "Unadjusted KRX Low and Close from the same daily source row",
                  "market_cap_basis": "Dated KRX Marcap in KRW; verified against Close * Stocks",
                  "listing_basis": "Dated KOSPI/KOSDAQ common share codes ending in 0; includes historical delistings",
                  "note": NOTE},
              "sources": [{"label": PROVIDER, "url": SOURCE_URL},
                          {"label": f"{day.year}년 고정 버전 원본", "url": info["url"]}]}
    validate_report(report)
    return report


def verified_source(path):
    info = json.loads(path.with_suffix(".source.json").read_text(encoding="utf-8"))
    if (not re.fullmatch(r"[a-f0-9]{40}", info.get("revision", ""))
            or info.get("url") != f"https://raw.githubusercontent.com/FinanceData/marcap/{info['revision']}/data/{path.name}"
            or info.get("year") != int(path.stem.split("-")[1])
            or hashlib.sha256(path.read_bytes()).hexdigest() != info.get("sha256")):
        raise ValueError(f"{path}: 원본 버전·날짜·체크섬이 일치하지 않습니다.")
    info.setdefault("fetched_at", datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat())
    return info


def restore_reports(reports, source_dir=SOURCE):
    """Validate the whole batch before adding anything; preserve saved sessions."""
    seen = set()
    closed = {item["date"] for item in closures()}
    writes = []
    for report in reports:
        validate_report(report)
        day = report["date"]
        if day in seen or day in closed:
            raise ValueError(f"중복 거래일 또는 휴장일입니다: {day}")
        seen.add(day)
        path = monthly_report_path(source_dir / "reports", "korea", day)
        if path.exists():
            validate_report(json.loads(path.read_text(encoding="utf-8")))
        else:
            writes.append((path, report))
    for path, report in writes:
        atomic_json(path, report)
    return len(writes)


def backfill(start, end, source_dirs, *, output=SOURCE, deps_dir=None):
    if start > end or end > datetime.now(timezone.utc).astimezone(ZoneInfo("Asia/Seoul")).date():
        raise ValueError("복원 날짜 범위가 잘못되었습니다.")
    if deps_dir:
        sys.path.insert(0, str(deps_dir))
    import pyarrow.parquet as pq

    reports, sources = [], []
    for year in range(start.year, end.year + 1):
        path = next((folder / f"marcap-{year}.parquet" for folder in source_dirs
                     if (folder / f"marcap-{year}.parquet").exists()), None)
        if path is None:
            raise ValueError(f"{year}년 원본이 없습니다. 다른 연도도 저장하지 않았습니다.")
        info = verified_source(path)
        sources.append(info)
        parquet = pq.ParquetFile(path)
        current, rows = None, []
        count = 0

        def flush():
            nonlocal count
            if rows:
                reports.append(report_from_rows(rows, current, info))
                count += 1

        for batch in parquet.iter_batches(batch_size=8192, columns=COLUMNS):
            for raw in batch.to_pylist():
                day = raw["Date"].date()
                if not start <= day <= end:
                    continue
                if current is not None and day < current:
                    raise ValueError(f"{path}: 거래일이 정렬되지 않았습니다.")
                if day != current:
                    flush()
                    current, rows = day, []
                rows.append(raw)
        flush()
        if not count:
            raise ValueError(f"{year}: 요청 범위의 거래일이 없습니다.")
        print(f"Validated {year}: {count} sessions", flush=True)
    added = restore_reports(reports, output)
    audit = {"schema_version": 1, "generated_at": datetime.now(timezone.utc).isoformat(),
             "requested_start": str(start), "requested_end": str(end), "added": added,
             "source_start": min(report["date"] for report in reports),
             "source_end": max(report["date"] for report in reports), "sources": sources,
             "sessions": [{"date": report["date"], "count": len(report["entries"]),
                           "counts": dict(Counter(row["exchange"] for row in report["entries"]))}
                          for report in reports]}
    atomic_json(output / "backfill-audit.json", audit)
    return audit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=date.fromisoformat, default=date(2018, 1, 1))
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--source-dir", type=Path, action="append", help="Annual Parquet directories in priority order")
    parser.add_argument("--output-dir", type=Path, default=SOURCE)
    parser.add_argument("--deps-dir", type=Path, help="Optional local installation of pyarrow")
    args = parser.parse_args()
    result = backfill(args.start, args.end, args.source_dir or [ROOT / "data/tmp_rebounds/source", ROOT / "data/tmp_korea_recalculation/source"],
                      output=args.output_dir, deps_dir=args.deps_dir)
    print(f"Added {result['added']} rebound sessions ({result['source_start']} to {result['source_end']})")


if __name__ == "__main__":
    main()
