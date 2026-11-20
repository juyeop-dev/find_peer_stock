"""Require checked-in calendar evidence before constructing historical sessions."""
from datetime import date, timedelta
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def verified_sessions(start, end, market, *, root=ROOT):
    start, end = date.fromisoformat(str(start)), date.fromisoformat(str(end))
    if end < start:
        raise ValueError("Calendar end precedes start")
    closed, opened = set(), set()
    for year in range(start.year, end.year + 1):
        path = Path(root) / f"data/market-closures/{year}.json"
        if not path.exists():
            raise ValueError(f"Verified {year} calendar missing: {path}")
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        if value.get("schema_version") != 1 or value.get("year") != year:
            raise ValueError(f"Calendar schema/year mismatch: {path}")
        rows = [row for row in value["markets"] if row["market"] == market]
        if len(rows) != 1 or not rows[0].get("source_urls"):
            raise ValueError(f"Calendar evidence missing or duplicated: {market}/{year}")
        row = rows[0]
        for target, days in [(closed, row["dates"]), (opened, row.get("additional_open_dates", {}))]:
            for day in days:
                parsed = date.fromisoformat(day)
                if parsed.year != year or parsed.isoformat() != day:
                    raise ValueError(f"Calendar contains an out-of-year date: {day}")
                target.add(parsed)
    if closed & opened:
        raise ValueError("Calendar marks a date both closed and open")
    result = []
    day = start
    while day <= end:
        if day not in closed and (day.weekday() < 5 or day in opened):
            result.append(day)
        if day == date.max:
            break
        day += timedelta(days=1)
    return result


def verified_european_closures(start, end, *, root=ROOT):
    path = Path(root) / "data/new-highs/europe-exchange-closures.json"
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if value.get("schema_version") != 1 or not isinstance(value.get("closures"), list):
        raise ValueError(f"Invalid European exchange calendar: {path}")
    for year in range(int(str(start)[:4]), int(str(end)[:4]) + 1):
        observed = {row["exchange"] for row in value["closures"]
                    if row["date"].startswith(f"{year:04d}-") and row.get("source_url")}
        if not {"EURONEXT", "LSE", "SIX", "XETR"} <= observed:
            raise ValueError(f"Verified European venue calendar missing for {year}")
    return value["closures"]
