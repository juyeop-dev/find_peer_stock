"""Collect actual KOFIA reporting dates without inferring exchange sessions."""
import argparse
from calendar import monthrange
from dataclasses import asdict
from datetime import date, datetime, timezone
import json
from pathlib import Path
import generate_credit_data as credit
from collection_request import collection_request
from history_policy import DEFAULT_POLICY


def month_windows(request):
    first, last = date.fromisoformat(request.start), date.fromisoformat(request.end)
    year, month = first.year, first.month
    while (year, month) <= (last.year, last.month):
        start, end = max(first, date(year, month, 1)), min(last, date(year, month, monthrange(year, month)[1]))
        complete = start.day == 1 and end.day == monthrange(year, month)[1]
        key = f"{year:04d}-{month:02d}" if complete else f"{start}_{end}"
        yield start, end, request.state / "credit" / f"{key}.json"
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)


def collect(request):
    rows = []
    for start, end, path in month_windows(request):
        if path.exists():
            raw = json.loads(path.read_bytes())
        else:
            raw = credit.fetch_range(start.strftime("%Y%m%d"), end.strftime("%Y%m%d"))
            credit.write_json(path, raw)
        raw_dates = [row.get("TMPV1") for row in raw if isinstance(row.get("TMPV1"), str) and len(row["TMPV1"]) == 8]
        if len(raw_dates) != len(set(raw_dates)):
            raise ValueError("Duplicated original KOFIA reporting dates")
        values = credit.normalize(raw)
        if not values or any(not str(start) <= row["date"] <= str(end) for row in values):
            raise ValueError(f"Missing or out-of-range KOFIA reporting month: {start}..{end}")
        rows.extend(values)
    if len({row["date"] for row in rows}) != len(rows):
        raise ValueError("Duplicated KOFIA reporting dates")
    for year in range(int(request.start[:4]), int(request.end[:4]) + 1):
        if request.start <= f"{year:04d}-01-01" and f"{year:04d}-12-31" <= request.end:
            if sum(row["date"].startswith(f"{year:04d}-") for row in rows) < 200:
                raise ValueError(f"Incomplete annual KOFIA reporting dates: {year}")
    previous = json.loads(credit.SOURCE.read_bytes())
    history = {row["date"]: row for row in rows}
    history.update({row["date"]: row for row in previous["history"]})
    now = datetime.now(timezone.utc).isoformat()
    value = {**previous, "generated_at": now, "latest_date": max(history), "history": [history[day] for day in sorted(history)]}
    credit.write_json(credit.SOURCE, value)
    credit.write_json(credit.PUBLISHED, value)
    credit.write_json(request.audit / "credit-progress.json", {"start": request.start, "end": request.end,
                      "reporting_dates": len(rows), "validated_at": now})
    return value


def main(argv=None, *, year=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, default=year)
    parser.add_argument("--history-config", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        request = collection_request(year=args.year, config=args.history_config, root=credit.ROOT)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    if args.dry_run:
        print(json.dumps({**asdict(request), "months": [[str(start), str(end), str(path)] for start, end, path in month_windows(request)]}, default=str))
        return
    value = collect(request)
    print(f"Retained {len(value['history'])} actual KOFIA reporting dates")


if __name__ == "__main__":
    main()
