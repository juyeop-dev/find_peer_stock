"""Add observed KOFIA reporting dates in 2021 without changing later balances."""
from calendar import monthrange
from datetime import datetime, timezone
import json

import generate_credit_data as credit


def main():
    cache = credit.ROOT / "data/tmp_2021/credit"
    rows = []
    for month in range(1, 13):
        path = cache / f"2021-{month:02d}.json"
        if path.exists():
            raw = json.loads(path.read_bytes())
        else:
            raw = credit.fetch_range(f"2021{month:02d}01", f"2021{month:02d}{monthrange(2021, month)[1]:02d}")
            credit.write_json(path, raw)
        values = credit.normalize(raw)
        if not values or any(not row["date"].startswith(f"2021-{month:02d}-") for row in values):
            raise ValueError(f"Missing or out-of-range KOFIA month: {month}")
        rows.extend(values)
    if len(rows) < 200 or len({row["date"] for row in rows}) != len(rows):
        raise ValueError("Incomplete or duplicated KOFIA reporting dates")
    previous = json.loads(credit.SOURCE.read_bytes())
    history = {row["date"]: row for row in rows}
    history.update({row["date"]: row for row in previous["history"]})
    now = datetime.now(timezone.utc).isoformat()
    result = {**previous, "generated_at": now, "history": [history[day] for day in sorted(history)]}
    credit.write_json(credit.SOURCE, result)
    credit.write_json(credit.PUBLISHED, result)
    credit.write_json(credit.ROOT / "data/information-audit/2021/credit-progress.json", {
        "start": "2021-01-01", "end": "2021-12-31", "reporting_dates": len(rows), "validated_at": now})
    print(f"Added {len(rows)} actual KOFIA reporting dates", flush=True)


if __name__ == "__main__":
    main()
