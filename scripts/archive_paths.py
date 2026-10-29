"""Paths for dated market archives."""

from __future__ import annotations

from datetime import date
import gzip
import hashlib
import json
from pathlib import Path

# Keep recent public JSON endpoints unchanged; historical reports are lossless.
COMPRESSED_BEFORE = "2026-01-01"


def monthly_report_path(root: Path, market: str, session: date | str) -> Path:
    day = session if isinstance(session, date) else date.fromisoformat(session)
    return root / market / f"{day:%Y_%m}" / f"{day.isoformat()}.json"


def publish_daily_report(path: Path, payload: dict, public_root: Path) -> None:
    """Publish historical reports as gzip, retaining prior generated JSON files.

    Durable reports in data/{kind}/reports remain ordinary JSON. Existing
    public copies are moved individually to a content-addressed local backup.
    """
    relative = path.resolve().relative_to(public_root.resolve())
    raw = (json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    if payload["date"] >= COMPRESSED_BEFORE:
        path.write_bytes(raw)
        return
    target = path.with_suffix(".json.gz")
    temporary = target.with_suffix(".gz.tmp")
    encoded = gzip.compress(raw, compresslevel=9, mtime=0)
    assert gzip.decompress(encoded) == raw
    temporary.write_bytes(encoded)
    temporary.replace(target)
    if path.exists():
        prior = path.read_bytes()
        backup_root = Path(__file__).resolve().parents[1] / "data/tmp_published_report_backup"
        backup_root.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(prior).hexdigest()
        backup = backup_root / f"{digest}.json"
        if backup.exists():
            assert backup.read_bytes() == prior, "Existing publication backup differs"
        path.replace(backup)
        with (backup_root / "manifest.jsonl").open("a", encoding="utf-8") as output:
            output.write(json.dumps({"path": relative.as_posix(), "sha256": digest}, ensure_ascii=False) + "\n")
