"""Paths for dated market archives."""

from __future__ import annotations

from datetime import date
import gzip
import hashlib
import json
from pathlib import Path
import time

# Keep recent public JSON endpoints unchanged; historical reports are lossless.
COMPRESSED_BEFORE = "2026-11-01"


def replace_publication(temporary: Path, target: Path) -> None:
    """Allow Windows readers/scanners to release a briefly locked publication."""
    for attempt in range(10):
        try:
            temporary.replace(target)
            return
        except PermissionError:
            if attempt == 9:
                raise
            time.sleep(.05 * (attempt + 1))


def monthly_report_path(root: Path, market: str, session: date | str) -> Path:
    day = session if isinstance(session, date) else date.fromisoformat(session)
    return root / market / f"{day:%Y_%m}" / f"{day.isoformat()}.json"


def publish_daily_report(path: Path, payload: dict, public_root: Path) -> None:
    """Publish historical reports as gzip, retaining prior generated JSON files.

    Durable reports in data/{kind}/reports remain ordinary JSON. Existing
    public copies are moved individually to a content-addressed local backup.
    """
    path.resolve().relative_to(public_root.resolve())
    raw = (json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    if payload["date"] >= COMPRESSED_BEFORE:
        path.write_bytes(raw)
        return
    publish_compressed_bytes(path, raw, public_root)


def publish_compressed_bytes(path: Path, raw: bytes, public_root: Path) -> None:
    """Publish exact bytes as gzip and preserve an existing public JSON copy."""
    relative = path.resolve().relative_to(public_root.resolve())
    path.parent.mkdir(parents=True, exist_ok=True)
    target = path.with_suffix(".json.gz")
    temporary = target.with_suffix(".gz.tmp")
    unchanged = False
    if target.exists():
        try:
            unchanged = gzip.decompress(target.read_bytes()) == raw
        except (OSError, EOFError):
            pass
    if not unchanged:
        encoded = gzip.compress(raw, compresslevel=9, mtime=0)
        assert gzip.decompress(encoded) == raw
        temporary.write_bytes(encoded)
        replace_publication(temporary, target)
    if path.exists():
        prior = path.read_bytes()
        backup_root = Path(__file__).resolve().parents[1] / "data/tmp_published_report_backup"
        backup_root.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(prior).hexdigest()
        backup = backup_root / f"{digest}.json"
        if backup.exists():
            assert backup.read_bytes() == prior, "Existing publication backup differs"
        replace_publication(path, backup)
        with (backup_root / "manifest.jsonl").open("a", encoding="utf-8") as output:
            output.write(json.dumps({"path": relative.as_posix(), "sha256": digest}, ensure_ascii=False) + "\n")
