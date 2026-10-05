"""Shared validation for optional close-to-close period returns."""

from __future__ import annotations

import math
import re
from datetime import date
from typing import Any


def validate_period_returns(entry: dict[str, Any], report_date: str, prefix: str) -> None:
    if "period_returns" not in entry:
        return
    periods = entry["period_returns"]
    if not isinstance(periods, dict):
        raise ValueError(f"{prefix}: period_returns must be an object")
    for period, value in periods.items():
        if not isinstance(period, str) or re.fullmatch(r"[1-9]\d*[dwmy]", period) is None:
            raise ValueError(f"{prefix}: invalid period key: {period!r}")
        if not isinstance(value, dict) or value.get("basis") != "close_to_close":
            raise ValueError(f"{prefix}: {period} must use close_to_close basis")
        change = value.get("change_pct")
        if type(change) not in (int, float) or not math.isfinite(change):
            raise ValueError(f"{prefix}: {period}.change_pct must be finite")
        try:
            start = date.fromisoformat(value["start_date"])
            end = date.fromisoformat(value["end_date"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"{prefix}: {period} needs valid start_date and end_date") from exc
        if not start < end or end.isoformat() != report_date:
            raise ValueError(f"{prefix}: {period} dates must end on the report date")
