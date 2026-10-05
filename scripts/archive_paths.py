"""Paths for dated market archives."""

from __future__ import annotations

from datetime import date
from pathlib import Path


def monthly_report_path(root: Path, market: str, session: date | str) -> Path:
    day = session if isinstance(session, date) else date.fromisoformat(session)
    return root / market / f"{day:%Y_%m}" / f"{day.isoformat()}.json"
