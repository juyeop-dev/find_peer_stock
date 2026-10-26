"""Restore dated Korean capitalization and actual daily trading values.

This is an explicit historical migration, never an intraday collector. The
FinanceData files mirror KRX daily data, whose amounts must not be described
as a 15:30-only snapshot. Original sector adjusted prices/returns are retained.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import json
import math
from pathlib import Path
import sys
import zipfile

from generate_turnover_data import load_markets, validate_report
from refresh_new_highs import atomic_json

ROOT = Path(__file__).resolve().parents[1]
VERSION = "korea-history-2026-10-25"
SOURCE = "KRX daily data via FinanceData/marcap"
SOURCE_URL = "https://github.com/FinanceData/marcap"
COLUMNS = ["Date", "Code", "Name", "Close", "ChangesRatio", "Volume", "Amount", "Marcap", "Stocks", "Market"]


def numeric(value, *, positive=False):
    return type(value) in (int, float) and math.isfinite(value) and value >= (1 if positive else 0)


def normalize_row(row):
    code = row["Code"]
    market = row["Market"].strip()
    if market.startswith("KOSDAQ"):
        market = "KOSDAQ"
    if market not in {"KOSPI", "KOSDAQ"} or not isinstance(code, str) or len(code) != 6:
        return None
    if not numeric(row["Close"], positive=True) or not numeric(row["Stocks"], positive=True):
        return None
    for field in ("Marcap", "Amount", "Volume"):
        if not numeric(row[field]):
            raise ValueError(f"{code}: invalid {field}")
    # The README's historic unit description is outdated. Validate every
    # actual row: modern Marcap is KRW, exactly close multiplied by shares.
    expected = row["Close"] * row["Stocks"]
    if abs(row["Marcap"] - expected) > max(1, expected * 1e-10):
        raise ValueError(f"{code}: capitalization unit/share-count mismatch")
    ratio = row["ChangesRatio"]
    if type(ratio) not in (int, float) or not math.isfinite(ratio):
        raise ValueError(f"{code}: invalid change ratio")
    return {"code": code, "name": row["Name"], "exchange": market, "price": row["Close"],
            "change_pct": ratio, "volume": row["Volume"], "turnover": row["Amount"],
            "market_cap": row["Marcap"], "shares": row["Stocks"]}


def extract_metrics(source_dir, cache_dir, dates):
    # Optional dependency needed only by this migration, not normal publishing.
    deps = ROOT / "data/tmp_korea_recalculation/deps"
    if deps.exists():
        sys.path.insert(0, str(deps))
    import pyarrow.parquet as pq

    cache_dir.mkdir(parents=True, exist_ok=True)
    sources, found = [], set()
    for year in sorted({day[:4] for day in dates}):
        path = source_dir / f"marcap-{year}.parquet"
        info = json.loads(path.with_suffix(".source.json").read_text(encoding="utf-8"))
        info["fetched_at"] = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
        if hashlib.sha256(path.read_bytes()).hexdigest() != info["sha256"]:
            raise ValueError(f"Source checksum changed: {path}")
        sources.append(info)
        current, rows, previous = None, {}, ""

        def flush():
            if current is not None and rows:
                if len(rows) < 1500:
                    raise ValueError(f"Incomplete source universe for {current}: {len(rows)}")
                atomic_json(cache_dir / f"{current}.json", {"date": current, "source": info, "rows": rows})
                found.add(current)

        for batch in pq.ParquetFile(path).iter_batches(batch_size=8192, columns=COLUMNS):
            for raw in batch.to_pylist():
                day = raw["Date"].date().isoformat()
                if day < previous:
                    raise ValueError("Source days are not sorted")
                previous = day
                if day not in dates:
                    continue
                if day != current:
                    flush()
                    current, rows = day, {}
                row = normalize_row(raw)
                if row is not None:
                    if row["code"] in rows:
                        raise ValueError(f"Duplicate {day}/{row['code']}")
                    rows[row["code"]] = row
        flush()
    return sources, found


def enrich_sector(snapshot, metrics, source_info):
    stocks, matched = [], 0
    for original in snapshot["stocks"]:
        stock = dict(original)
        row = metrics.get(stock.get("code", stock["ticker"].split(".")[0]))
        if row is not None and stock["date"] == snapshot["date"]:
            # Do not combine today's cap or an adjusted close * today's shares
            # with historical returns. These are the actually dated amounts.
            stock.update(market_cap=row["market_cap"], turnover=row["turnover"],
                         market_cap_date=snapshot["date"], monetary_source=SOURCE)
            matched += 1
        stocks.append(stock)
    if matched < sum(stock["date"] == snapshot["date"] for stock in stocks) * .98:
        raise ValueError(f"Low dated capitalization coverage: {snapshot['date']} {matched}/{len(stocks)}")
    result = {**snapshot, "stocks": stocks, "historical_metrics": {
        "version": VERSION, "date": snapshot["date"], "provider": SOURCE, "source_url": SOURCE_URL,
        "source_revision": source_info["revision"], "source_sha256": source_info["sha256"],
        "matched": matched, "unmatched": len(stocks) - matched, "currency": "KRW",
        "turnover_basis": "KRX daily amount; a 15:30-only cutoff is not asserted",
        "price_basis": "Original adjusted prices and period returns retained",
    }}
    if snapshot.get("reconstruction"):
        result["reconstruction"] = {**snapshot["reconstruction"], "market_cap_restored": True,
            "turnover_restored": True}
        # Kept in Korean here so the public explanation matches the UI.
        result["reconstruction"]["note"] = (
            "현재 업종 분류 기준으로 과거 조정 주가를 재구성한 자료입니다. 당시 구성 종목 전체와 다를 수 있습니다. "
            "시가총액과 거래대금은 해당 날짜의 KRX 일별 확정 자료로 보완했습니다. 거래대금은 시간외가 포함될 수 있어 15:30 시점 자료와 구분합니다.")
    return result


def daily_turnover(report, metrics, source_info, classifications):
    candidates = sorted((row for row in metrics.values() if row["turnover"] > 0),
                        key=lambda row: (-row["turnover"], row["code"]))[:30]
    if len(candidates) != 30:
        raise ValueError(f"Incomplete top 30: {report['date']}")
    originals = {entry["ticker"].split(".")[0]: entry for entry in report["entries"]}
    entries = []
    for rank, row in enumerate(candidates, 1):
        code = row["code"]
        old = originals.get(code, {})
        classification = classifications.get(code, classifications.get(code[:-1] + "0", {}))
        suffix = ".KS" if row["exchange"] == "KOSPI" else ".KQ"
        entries.append({"rank": rank, "ticker": code + suffix, "name": row["name"], "exchange": row["exchange"],
            "price": row["price"], "change_pct": row["change_pct"], "turnover": row["turnover"],
            "market_cap": row["market_cap"], "market_cap_date": report["date"], "currency": "KRW",
            "turnover_currency": "KRW", "market_cap_currency": "KRW", "source_symbol": f"KRX:{code}",
            "sector": classification.get("sector", old.get("sector", "Unclassified")),
            "industry": classification.get("industry", old.get("industry", "Unclassified")),
            **({"logo_url": old["logo_url"]} if "logo_url" in old else {}),
            **({"period_returns": old["period_returns"]} if "period_returns" in old else {})})
    return {"schema_version": 1, "market": "korea", "date": report["date"],
        "summary": "KRX 일별 확정 거래대금 기준 상위 30개 종목입니다. 시간외가 포함될 수 있어 정규장 15:30 시점 순위와 구분합니다.",
        "entries": entries, "sources": [{"label": SOURCE, "url": SOURCE_URL}],
        "source_metadata": {"provider": SOURCE, "fetched_at": source_info.get("fetched_at"),
            "ranking": "KRX Amount descending; KOSPI/KOSDAQ stocks including preferred; ETFs/KONEX excluded",
            "session": "daily", "currency": "KRW", "source_revision": source_info["revision"],
            "source_sha256": source_info["sha256"], "session_symbols": len(metrics),
            "recalculation_version": VERSION,
            "previous_provider": report.get("source_metadata", {}).get("previous_provider", report.get("source_metadata", {}).get("provider")),
            "previous_fetched_at": report.get("source_metadata", {}).get("previous_fetched_at", report.get("source_metadata", {}).get("fetched_at"))}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=ROOT / "data/tmp_korea_recalculation/source")
    parser.add_argument("--apply", action="store_true", help="Write validated replacements after backing up originals")
    parser.add_argument("--start", help="Limit the migration to ISO dates on or after this date")
    parser.add_argument("--end", help="Limit the migration to ISO dates on or before this date")
    parser.add_argument("--audit-tag", default="2026-10-25", help="Name for this migration's independent audit and backup")
    args = parser.parse_args()
    cache = ROOT / "data/tmp_korea_recalculation/metrics"
    sector_paths = sorted((ROOT / "data/sectors/daily").glob("*.json.gz"))
    turnover_paths = sorted((ROOT / "data/turnover/reports/korea").rglob("*.json"))
    sectors = [(path, json.loads(gzip.decompress(path.read_bytes()))) for path in sector_paths]
    turnover = [(path, json.loads(path.read_text(encoding="utf-8"))) for path in turnover_paths]
    if args.start or args.end:
        selected = lambda item: (not args.start or item[1]["date"] >= args.start) and (not args.end or item[1]["date"] <= args.end)
        sectors = [item for item in sectors if selected(item)]
        turnover = [item for item in turnover if selected(item)]
    dates = {data["date"] for _, data in sectors + turnover}
    source_infos, found = extract_metrics(args.source_dir, cache, dates)
    latest = json.loads((ROOT / "data/sectors/index.json").read_text(encoding="utf-8"))
    classifications = {s["code"]: s for s in latest["stocks"]}
    markets_dir = ROOT / "data/turnover"
    markets = {market["id"]: market for market in load_markets(markets_dir)}
    changes, audit = [], {"schema_version": 1, "version": VERSION, "sources": source_infos,
        "calculated_at": datetime.now(timezone.utc).isoformat(),
        "source_dates": len(found), "missing_source_dates": sorted(dates - found), "sectors": [], "turnover": []}
    for path, snapshot in sectors:
        if snapshot["date"] not in found:
            continue
        source = json.loads((cache / f"{snapshot['date']}.json").read_text(encoding="utf-8"))
        if source["date"] != snapshot["date"]:
            raise ValueError("Sector/source date mismatch")
        enriched = enrich_sector(snapshot, source["rows"], source["source"])
        changes.append((path, gzip.compress(json.dumps(enriched, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode(), mtime=0)))
        audit["sectors"].append({"date": snapshot["date"], "matched": enriched["historical_metrics"]["matched"],
                               "unmatched": enriched["historical_metrics"]["unmatched"]})
    for path, report in turnover:
        if report["date"] not in found:
            audit["turnover"].append({"date": report["date"], "replaced": False, "reason": "Source has not published this date; original snapshot retained"})
            continue
        source = json.loads((cache / f"{report['date']}.json").read_text(encoding="utf-8"))
        if source["date"] != report["date"]:
            raise ValueError("Turnover/source date mismatch")
        result = daily_turnover(report, source["rows"], source["source"], classifications)
        validate_report(result, path, markets_dir / "reports", markets)
        changed = len({e["ticker"] for e in result["entries"]} - {e["ticker"] for e in report["entries"]})
        audit["turnover"].append({"date": report["date"], "replaced": True, "new_constituents": changed,
            "previous_total": sum(e["turnover"] for e in report["entries"]), "total": sum(e["turnover"] for e in result["entries"])})
        changes.append((path, (json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()))
    if not args.audit_tag or any(char not in "0123456789abcdefghijklmnopqrstuvwxyz-" for char in args.audit_tag):
        parser.error("Invalid audit tag")
    target = ROOT / "data/korea-history-recalculation" / f"{args.audit_tag}.json"
    if args.apply:
        backup = ROOT / "data/tmp_korea_recalculation" / f"originals-before-{args.audit_tag}.zip"
        if not backup.exists():
            with zipfile.ZipFile(backup, "w", zipfile.ZIP_DEFLATED) as archive:
                for path, _ in sectors + turnover:
                    archive.write(path, path.relative_to(ROOT))
        for path, content in changes:
            temporary = path.with_suffix(path.suffix + ".tmp")
            temporary.write_bytes(content)
            temporary.replace(path)
        atomic_json(target, audit)
    print(json.dumps({"applied": args.apply, "sector_dates": len(audit["sectors"]),
        "turnover_replaced": sum(row["replaced"] for row in audit["turnover"]),
        "missing_source_dates": audit["missing_source_dates"], "planned_files": len(changes)}))


if __name__ == "__main__":
    main()
