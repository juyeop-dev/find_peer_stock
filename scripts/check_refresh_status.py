"""Check the age of a published snapshot without changing any site data."""

from __future__ import annotations

import argparse
import http.client
import json
import math
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any


DEFAULT_SITE_URL = "https://juyeop-dev.github.io/find_peer_stock/"
DEFAULT_MAX_AGE_MINUTES = 20.0


def evaluate_refresh_status(
    payload: Any,
    *,
    now: datetime,
    max_age_minutes: float = DEFAULT_MAX_AGE_MINUTES,
) -> dict[str, Any]:
    """Reject missing, naive or future timestamps; the age limit is inclusive."""
    if not math.isfinite(max_age_minutes) or max_age_minutes <= 0:
        raise ValueError("max_age_minutes must be a finite number greater than zero")
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must include a timezone")
    generated_value = payload.get("generated_at") if isinstance(payload, dict) else None
    if not isinstance(generated_value, str) or not generated_value.strip():
        raise ValueError("generated_at must be a nonempty ISO 8601 timestamp")
    try:
        generated_at = datetime.fromisoformat(generated_value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("generated_at must be a valid ISO 8601 timestamp") from exc
    if generated_at.tzinfo is None or generated_at.utcoffset() is None:
        raise ValueError("generated_at must include a timezone")

    age_seconds = (
        now.astimezone(timezone.utc) - generated_at.astimezone(timezone.utc)
    ).total_seconds()
    if age_seconds < 0:
        raise ValueError("generated_at is in the future; check the snapshot and local clock")
    age_minutes = age_seconds / 60
    stale = age_minutes > max_age_minutes
    return {
        "generated_at": generated_at.isoformat(),
        "age_minutes": round(age_minutes, 6),
        "max_age_minutes": max_age_minutes,
        "stale": stale,
        "status": "stale" if stale else "fresh",
    }


def fetch_site_index(site_url: str) -> Any:
    parts = urllib.parse.urlsplit(site_url)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ValueError("site-url must be an absolute HTTP or HTTPS URL")
    path = parts.path.rstrip("/")
    if not path.endswith("/data/index.json"):
        path += "/data/index.json"
    query = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    query.append(("_refresh_check", str(time.time_ns())))
    url = urllib.parse.urlunsplit(
        (parts.scheme, parts.netloc, path, urllib.parse.urlencode(query), "")
    )
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "Cache-Control": "no-cache, no-store",
            "Pragma": "no-cache",
            "User-Agent": "stock-peer-site-refresh-check",
        },
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site-url", default=DEFAULT_SITE_URL,
                        help="Site base URL or its full /data/index.json URL.")
    parser.add_argument("--max-age-minutes", type=float, default=DEFAULT_MAX_AGE_MINUTES,
                        help="Maximum snapshot age; exactly this age is fresh (default: 20).")
    args = parser.parse_args(argv)
    try:
        if not math.isfinite(args.max_age_minutes) or args.max_age_minutes <= 0:
            raise ValueError("max-age-minutes must be a finite number greater than zero")
        payload = fetch_site_index(args.site_url)
        result = evaluate_refresh_status(
            payload, now=datetime.now(timezone.utc), max_age_minutes=args.max_age_minutes
        )
    except (OSError, ValueError, http.client.HTTPException) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}), file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 1 if result["stale"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
