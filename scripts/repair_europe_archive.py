"""One-time, recoverable repair of the September 2026 European archive.

Yahoo's historical mapping covered only 3,592/5,411 scanned listings and its
mixed-currency turnover ranking compared GBX with EUR/CHF at face value.
Move those reports out of the published source tree. Keep their originals in
data/review/europe and remove only their regenerable published copies.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
REVIEW = DATA / "review" / "europe"
YAHOO_DATES = {
    "new-highs": (
        "2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04",
        "2026-09-07", "2026-09-08", "2026-09-09", "2026-09-10", "2026-09-15",
    ),
    "turnover": (
        "2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04",
        "2026-09-07", "2026-09-08", "2026-09-09", "2026-09-10",
        "2026-09-11", "2026-09-14", "2026-09-15", "2026-09-16", "2026-09-17",
    ),
}


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, payload: dict) -> None:
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def main() -> None:
    moves: list[tuple[Path, Path]] = []
    for category, dates in YAHOO_DATES.items():
        for day in dates:
            source = DATA / category / "reports" / "europe" / f"{day}.json"
            archived = REVIEW / category / f"{day}.json"
            if source.exists():
                if archived.exists():
                    raise ValueError(f"archive destination already exists: {archived}")
                if read(source).get("source_metadata", {}).get("provider") != "Yahoo Finance chart history":
                    raise ValueError(f"refusing to archive non-Yahoo report: {source}")
                moves.append((source, archived))
            elif not archived.exists():
                raise ValueError(f"neither source nor archived report exists: {source}")

    remaining = sorted((DATA / "turnover" / "reports" / "europe").glob("*.json"))
    for path in remaining:
        if path in {source for source, _ in moves}:
            continue
        if read(path).get("source_metadata", {}).get("provider") != "TradingView public scanner":
            raise ValueError(f"unexpected remaining turnover provider: {path}")

    for source, archived in moves:
        archived.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(archived))

    for category, dates in YAHOO_DATES.items():
        for day in dates:
            for published_root in (DATA / "generated", ROOT / "frontend" / "public" / "data"):
                published = published_root / category / "europe" / f"{day}.json"
                published.unlink(missing_ok=True)

    updated = 0
    for path in (DATA / "turnover" / "reports" / "europe").glob("*.json"):
        report = read(path)
        if report.get("source_metadata", {}).get("provider") != "TradingView public scanner":
            raise ValueError(f"unexpected turnover provider: {path}")
        for entry in report["entries"]:
            entry["turnover_currency"] = "USD"
            entry["market_cap_currency"] = "USD"
        report["source_metadata"]["turnover_currency"] = "USD"
        report["source_metadata"]["market_cap_currency"] = "USD"
        report["summary"] = "장 마감 후 TradingView 주식 스크리너의 거래대금 상위 30개 종목입니다. 거래대금과 시가총액은 미달러 환산값이며 주가는 종목별 표시 통화입니다."
        write(path, report)
        updated += 1
    print(f"Archived {len(moves)} unverified Yahoo reports; updated {updated} TradingView turnover reports")


if __name__ == "__main__":
    main()
