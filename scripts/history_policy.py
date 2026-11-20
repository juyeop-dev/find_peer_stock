"""Validate collection policy and inspect dates without collecting or publishing data."""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import json
import math
from pathlib import Path
import re

DEFAULT_POLICY = Path(__file__).resolve().parents[1] / "config/history-policy.json"
SAFE_INTEGER = 2**53 - 1


class HistoryPolicyError(ValueError):
    pass


def _keys(value, expected, name):
    if not isinstance(value, dict) or set(value) != set(expected):
        raise HistoryPolicyError(f"{name} must contain exactly: {', '.join(expected)}")


def _integer(value, name, minimum=0, maximum=SAFE_INTEGER):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or abs(value) > SAFE_INTEGER or not math.isfinite(value)
            or int(value) != value or not minimum <= value <= maximum):
        raise HistoryPolicyError(f"{name} must be an integer between {minimum} and {maximum}")
    return int(value)


def _as_of(value):
    if value is None:
        return datetime.now(timezone.utc).date()
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    raise HistoryPolicyError("as_of must be a real calendar date in YYYY-MM-DD format")


def resolve_history_policy(value, *, as_of=None):
    """Return a collection request, never evidence of published data coverage.

    An omitted end year follows the UTC date at execution. A current-year
    request ends on as_of; a completed year ends on December 31.
    """
    _keys(value, ["schema_version", "collection", "publication"], "policy")
    if _integer(value["schema_version"], "schema_version", 1) != 1:
        raise HistoryPolicyError("unsupported policy schema_version")
    collection, publication = value["collection"], value["publication"]
    _keys(collection, ["start_year", "end_year", "price_reference_days"], "collection")
    _keys(publication, ["manifest_version"], "publication")
    if _integer(publication["manifest_version"], "manifest_version", 1) != 1:
        raise HistoryPolicyError("unsupported publication manifest_version")
    today = _as_of(as_of)
    first = _integer(collection["start_year"], "start_year", 1, 9999)
    last = (today.year if collection["end_year"] is None else
            _integer(collection["end_year"], "end_year", 1, 9999))
    reference_days = _integer(collection["price_reference_days"], "price_reference_days")
    if first > last or last > today.year:
        raise HistoryPolicyError("collection requires start_year <= end_year <= as_of year")
    start = date(first, 1, 1)
    end = min(date(last, 12, 31), today)
    try:
        reference = start - timedelta(days=reference_days)
    except (OverflowError, ValueError) as error:
        raise HistoryPolicyError("price reference date is outside years 0001..9999") from error
    return {
        "policy_schema_version": 1,
        "publication_manifest_version": 1,
        "as_of": today.isoformat(),
        "collection": {
            "start_year": first, "end_year": last,
            "start_date": start.isoformat(), "end_date": end.isoformat(),
            "price_reference_days": reference_days,
            "price_reference_start": reference.isoformat(),
        },
    }


def _reject_constant(value):
    raise HistoryPolicyError(f"non-JSON number: {value}")


def load_history_policy(path=DEFAULT_POLICY, *, as_of=None):
    value = json.loads(Path(path).read_text(encoding="utf-8-sig"), parse_constant=_reject_constant)
    return resolve_history_policy(value, as_of=as_of)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--as-of", help="UTC date for reproducible inspection (YYYY-MM-DD)")
    args = parser.parse_args()
    try:
        result = load_history_policy(args.config, as_of=args.as_of)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
