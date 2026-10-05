"""Validate official, dated market closures shared by both calendar archives."""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


def load_scheduled_closures(calendar_dir: Path, known_markets: set[str]) -> list[dict[str, str]]:
    if not calendar_dir.exists():
        return []
    closures: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for path in sorted(calendar_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError(f"{path}: invalid closure calendar: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"{path}: expected a closure calendar object")
        year, markets = payload.get("year"), payload.get("markets")
        if (payload.get("schema_version") != 1 or type(year) is not int or
                path.name != f"{year:04d}.json" or not isinstance(markets, list)):
            raise ValueError(f"{path}: expected a schema_version 1 annual closure calendar")
        for market in markets:
            if (not isinstance(market, dict) or not isinstance(market.get("market"), str) or
                    market["market"] not in known_markets):
                raise ValueError(f"{path}: unknown market")
            market_id = market["market"]
            urls, dates = market.get("source_urls"), market.get("dates")
            if (not isinstance(urls, list) or not urls or
                    any(not isinstance(url, str) or urlsplit(url).scheme != "https" or
                        not urlsplit(url).hostname for url in urls) or
                    not isinstance(dates, dict)):
                raise ValueError(f"{path}: {market_id} needs official HTTPS sources and dated closures")
            for key, reason in dates.items():
                if not isinstance(key, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", key):
                    raise ValueError(f"{path}: invalid closure date: {key}")
                try:
                    day = date.fromisoformat(key)
                except ValueError as exc:
                    raise ValueError(f"{path}: invalid closure date: {key}") from exc
                if (day.year != year or day.weekday() >= 5 or not isinstance(reason, str) or
                        not reason.strip() or (market_id, key) in seen):
                    raise ValueError(f"{path}: invalid or duplicate weekday closure: {market_id} {key}")
                seen.add((market_id, key))
                closures.append({"market": market_id, "date": key, "label": "휴장", "reason": reason.strip()})
    return closures


def merge_closures(scheduled: list[dict[str, str]], inferred: list[dict[str, str]],
                   reports: list[dict[str, Any]]) -> list[dict[str, str]]:
    recorded = {(report["market"], report["date"]) for report in reports}
    by_key = {(closure["market"], closure["date"]): closure for closure in inferred}
    by_key.update({(closure["market"], closure["date"]): closure for closure in scheduled})
    return [
        by_key[key] for key in sorted(by_key, key=lambda item: (item[1], item[0]), reverse=True)
        if key not in recorded
    ]
