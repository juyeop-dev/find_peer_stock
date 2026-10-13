"""Publish daily Korean margin loan balances from KOFIA FreeSIS."""

from __future__ import annotations

import json
import os
import urllib.request
from calendar import monthrange
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data" / "credit" / "index.json"
PUBLISHED = ROOT / "frontend" / "public" / "data" / "credit" / "index.json"
KST = ZoneInfo("Asia/Seoul")
ENDPOINT = "https://freesis.kofia.or.kr/meta/getMetaDataList.do"
SOURCE_PAGE = "https://freesis.kofia.or.kr/stat/FreeSIS.do?parentDivId=MSIS10000000000000&serviceId=STATSCU0100000070"


def fetch_range(start_date: str, end_date: str) -> list[dict]:
    search = {"tmpV40": "1000000", "tmpV41": "1", "tmpV6": "2", "tmpV7": "1",
              "tmpV4": "", "tmpV11": "", "tmpV1": "RD", "tmpV45": start_date,
              "tmpV46": end_date, "OBJ_NM": "STATSCU0100000070BO"}
    request = urllib.request.Request(ENDPOINT, data=json.dumps({"dmSearch": search}).encode("utf-8"),
        headers={"User-Agent": "Mozilla/5.0 (compatible; StockPeerSite/1.0)",
                 "Content-Type": "application/json; charset=UTF-8", "Referer": SOURCE_PAGE})
    with urllib.request.urlopen(request, timeout=25) as response:
        payload = json.load(response)
    rows = payload.get("ds1")
    if not isinstance(rows, list):
        raise ValueError(f"KOFIA response for {start_date} has no daily rows")
    return rows


def normalize(rows: list[dict]) -> list[dict]:
    by_date = {}
    for row in rows:
        raw_date = row.get("TMPV1")
        if not isinstance(raw_date, str) or len(raw_date) != 8 or not raw_date.isdigit():
            continue
        date = datetime.strptime(raw_date, "%Y%m%d").date().isoformat()
        total, kospi, kosdaq = (row.get(key) for key in ("TMPV2", "TMPV3", "TMPV4"))
        if not all(isinstance(value, (int, float)) and value >= 0 for value in (total, kospi, kosdaq)):
            continue
        if abs(total - kospi - kosdaq) > 1:
            raise ValueError(f"KOFIA market balances do not sum on {date}")
        by_date[date] = {"date": date, "total": total, "kospi": kospi, "kosdaq": kosdaq}
    return [by_date[date] for date in sorted(by_date)]


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def generate(now: datetime | None = None, source: Path = SOURCE, published: Path = PUBLISHED) -> dict:
    now = now or datetime.now(tz=KST)
    end_date = now.strftime("%Y%m%d")
    existing = json.loads(source.read_text(encoding="utf-8")) if source.exists() else {}
    previous_year, previous_month = (now.year - 1, 12) if now.month == 1 else (now.year, now.month - 1)
    rows = []
    first_year = previous_year if existing.get("history") else now.year - 2
    for year in range(first_year, now.year + 1):
        for month in range(1, 13):
            if existing.get("history") and (year, month) < (previous_year, previous_month):
                continue
            start = f"{year}{month:02d}01"
            if start > end_date:
                break
            end = min(f"{year}{month:02d}{monthrange(year, month)[1]:02d}", end_date)
            rows.extend(fetch_range(start, end))
    by_date = {row["date"]: row for row in existing.get("history", [])}
    by_date.update({row["date"]: row for row in normalize(rows)})
    history = [by_date[date] for date in sorted(by_date)]
    if len(history) < 100:
        raise ValueError(f"Only {len(history)} KOFIA credit balance rows available")
    if history == existing.get("history"):
        if not published.exists():
            write_json(published, existing)
        print(f"Credit balance unchanged through {history[-1]['date']}")
        return existing
    payload = {"generated_at": now.isoformat(), "latest_date": history[-1]["date"],
               "unit": "KRW million", "metric": "margin loan balance (신용거래융자 잔고)",
               "source": "KOFIA FreeSIS", "source_url": SOURCE_PAGE, "history": history}
    write_json(source, payload)
    write_json(published, payload)
    print(f"Credit balance: {len(history)} dates through {history[-1]['date']}")
    return payload


if __name__ == "__main__":
    generate()
