"""Package public data losslessly into bounded standard USTAR assets and hashed indexes.

Never collects data, deletes originals, or uploads anything. The active pointer
is changed only after full source/round-trip verification and file-limit checks.
"""
from __future__ import annotations
import argparse
from collections import defaultdict
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import tarfile
import tempfile
from datetime import datetime, timezone
import re
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
MIB = 1024 * 1024
MAX_FILES, MAX_ASSET = 20_000, 25 * MIB
KINDS = {"stock-history", "stock-information", "new-highs", "turnover", "credit", "investors", "sectors",
         "semiconductor", "calendar-stocks", "rebounds", "stocks", "chart-replay"}
HEADERS = "/*\n  Access-Control-Allow-Origin: *\n  X-Content-Type-Options: nosniff\n\n/manifest.json\n  Cache-Control: no-cache\n\n/blobs/*\n  Cache-Control: public, max-age=31536000, immutable\n\n/indexes/*\n  Cache-Control: public, max-age=31536000, immutable\n\n/manifests/*\n  Cache-Control: public, max-age=31536000, immutable\n"


def workspace_directory(parent, prefix):
    # Windows Python 3.13+ gives mkdtemp a private DACL. Public review artifacts
    # must inherit the workspace ACL so the user can inspect them afterwards.
    path = Path(parent) / (prefix + uuid.uuid4().hex[:12])
    path.mkdir(mode=0o755)
    return path


def canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def valid_path(value):
    return (isinstance(value, str) and value and not value.startswith("/") and "\\" not in value
            and not any(ord(char) < 32 or char in ':?#%' for char in value)
            and all(part not in {"", ".", ".."} and not part.startswith(".") for part in value.split("/")))


def validate_publication(value):
    try:
        when = datetime.fromisoformat(value['evidence']['verified_at'].replace('Z', '+00:00'))
        if (value['schema_version'] != 1 or not value['revision'] or
                not re.fullmatch('[a-f0-9]{64}', value['evidence']['sha256']) or
                when.tzinfo is None or when > datetime.now(timezone.utc) or not isinstance(value['kinds'], dict)):
            raise ValueError('Invalid publication evidence')
        for row in value['kinds'].values():
            if (any(type(row[key]) is not int for key in ['selection_start_year', 'selection_end_year', 'published_items']) or
                    not 1 <= row['selection_start_year'] <= row['selection_end_year'] < when.year or
                    row['published_items'] < 1 or row['scope'] != 'observed_with_listing_exceptions'):
                raise ValueError('Invalid published range')
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError('Verified publication metadata required') from exc
    return value


def verify_publication_evidence(publication, proof=None):
    from generate_publication_history import from_deployment
    evidence_path = publication.get('evidence', {}).get('path')
    if not valid_path(evidence_path): raise ValueError('Verified publication evidence path required')
    path = Path(proof).resolve() if proof else (ROOT/evidence_path).resolve()
    if not proof and not path.is_relative_to(ROOT): raise ValueError('Publication proof escapes source directory')
    raw = path.read_bytes()
    if digest(raw) != publication['evidence']['sha256'] or from_deployment(raw,evidence_path) != publication:
        raise ValueError('Publication metadata differs from completed audit/deployment evidence')
    return True


def source_files(source):
    for directory, folders, files in os.walk(source, followlinks=False):
        folders.sort(); files.sort()
        for name in folders + files:
            path = Path(directory) / name
            if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
                raise ValueError(f"Public input must not contain filesystem links: {path}")
        for name in files:
            path = Path(directory) / name
            logical = path.relative_to(source).as_posix()
            first = logical.split("/")[0]
            if (not valid_path(logical) or not logical.endswith((".json", ".json.gz"))
                    or ("/" in logical and first not in KINDS)
                    or ("/" not in logical and name not in {"index.json", "index.json.gz", "chart-catalog.json.gz", "chart-catalog.json"})):
                raise ValueError(f"Input is not an approved public-data path: {logical}")
            stat = path.stat()
            if not stat.st_size:
                raise ValueError(f"Empty public artifact: {logical}")
            yield logical, path, stat.st_size, stat.st_mtime_ns


def group_key(path):
    parts = path.split("/")
    dated = parts[0] in {'new-highs', 'turnover', 'rebounds', 'sectors'}
    year = next((part[:4] for part in parts if re.fullmatch(r'\d{4}(?:-\d{2}-\d{2}|_\d{2})?(?:\.json(?:\.gz)?)?', part)), None) if dated else None
    return (parts[0], parts[1] if len(parts) > 2 else "", year or digest(path.encode())[:2])


def write_blob(staging, raw, category, suffix):
    sha = digest(raw)
    relative = f"{category}/{sha}{suffix}"
    target = staging / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if target.read_bytes() != raw:
            raise ValueError("Content-addressed asset changed")
    else:
        target.write_bytes(raw)
    return {"path": relative, "sha256": sha, "size": len(raw)}


def make_tar(rows):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w", format=tarfile.USTAR_FORMAT, encoding="utf-8") as archive:
        for path, raw in rows:
            item = tarfile.TarInfo(path)
            item.size, item.mode, item.mtime = len(raw), 0o644, 0
            item.uid = item.gid = 0
            item.uname = item.gname = ""
            archive.addfile(item, io.BytesIO(raw))
    return output.getvalue()


def referenced_assets(directory, manifest):
    result = set()
    for descriptor in manifest["shards"].values():
        relative = descriptor["path"]
        if not valid_path(relative):
            raise ValueError("Invalid prior index path")
        raw = (directory / relative).read_bytes()
        if digest(raw) != descriptor["sha256"]:
            raise ValueError("Prior index checksum differs")
        result.add(relative)
        for entry in json.loads(raw)["entries"].values():
            for asset in ([entry["container"]] if entry["format"] == "ustar-v1" else entry["parts"]):
                if not valid_path(asset["path"]):
                    raise ValueError("Invalid prior asset path")
                result.add(asset["path"])
    return result


def verify_roundtrip(staging, entries, originals):
    containers = defaultdict(list)
    for logical, entry in entries.items():
        if entry["format"] == "ustar-v1":
            containers[entry["container"]["path"]].append(logical)
        else:
            value = hashlib.sha256(); size = 0
            for part in entry["parts"]:
                raw = (staging / part["path"]).read_bytes()
                if digest(raw) != part["sha256"] or len(raw) != part["size"]:
                    raise ValueError(f"Raw asset checksum differs: {logical}")
                value.update(raw); size += len(raw)
            if value.hexdigest() != entry["sha256"] or size != entry["size"]:
                raise ValueError(f"Segment reconstruction differs: {logical}")
    for container, paths in containers.items():
        raw = (staging / container).read_bytes()
        if digest(raw) != entries[paths[0]]["container"]["sha256"]:
            raise ValueError("Bundle checksum differs")
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:", encoding="utf-8") as archive:
            actual = archive.getnames()
            if sorted(actual) != sorted(paths) or len(actual) != len(set(actual)):
                raise ValueError("Bundle membership differs")
            for logical in paths:
                member = archive.getmember(logical)
                if not member.isfile() or digest(archive.extractfile(member).read()) != entries[logical]["sha256"]:
                    raise ValueError(f"Bundle reconstruction differs: {logical}")
    for logical, path, size, modified in originals:
        stat = path.stat()
        # Compare the source again after packing, not just an in-memory copy.
        if stat.st_size != size or stat.st_mtime_ns != modified or digest(path.read_bytes()) != entries[logical]["sha256"]:
            raise ValueError(f"Original changed during packaging: {logical}")


def package(source, output, *, publication=None, bundle_bytes=2 * MIB, direct_threshold=128 * 1024,
            max_files=MAX_FILES, max_asset_bytes=MAX_ASSET, previous=None, publication_proof=None, require_evidence=False):
    source, output = Path(source).resolve(), Path(output).resolve()
    if not source.is_dir() or source == output or source.is_relative_to(output) or output.is_relative_to(source):
        raise ValueError("Public source and output must be separate, non-overlapping directories")
    if (not 10240 <= bundle_bytes < max_asset_bytes or not 0 < direct_threshold <= max_asset_bytes
            or not 0 < max_files <= MAX_FILES or not 0 < max_asset_bytes <= MAX_ASSET):
        raise ValueError("Invalid or non-free publication limits")
    default_publication = publication is None
    publication = validate_publication(publication if publication is not None else json.loads((ROOT / "shared/published-history.json").read_bytes()))
    evidence_verified = verify_publication_evidence(publication,publication_proof) if default_publication or require_evidence else False
    originals = list(source_files(source))
    if not originals:
        raise ValueError("No public artifacts")
    # The old deployment receipt gives global listing counts. Reject an older,
    # incomplete worktree as the source of that already verified publication.
    for kind, folder in [("stock_history", "stock-history"), ("financials", "stock-information")]:
        if kind in publication["kinds"]:
            names = {logical.split("/")[-1].replace(".delta-v1.json.gz", "").replace(".json.gz", "").replace(".json", "")
                     for logical, *_ in originals if logical.startswith(folder + "/")}
            if len(names) < publication["kinds"][kind]["published_items"]:
                raise ValueError(f"Source is missing verified {kind} listings")
    output.mkdir(parents=True, exist_ok=True)
    staging = workspace_directory(output, '.build-')
    groups, entries = defaultdict(list), {}
    for row in originals:
        groups[group_key(row[0])].append(row)
    for group_number, group in enumerate(sorted(groups), 1):
        pending, pending_bytes = [], 0
        def flush():
            nonlocal pending, pending_bytes
            if not pending:
                return
            container = write_blob(staging, make_tar(pending), "blobs", ".tar")
            for logical, raw in pending:
                entries[logical] = {"format": "ustar-v1", "size": len(raw), "sha256": digest(raw),
                                    "container": container, "entry": logical}
            pending, pending_bytes = [], 0
        for logical, path, size, modified in sorted(groups[group]):
            if size >= direct_threshold or size > bundle_bytes - 10240:
                flush(); parts = []; value = hashlib.sha256()
                with path.open("rb") as input:
                    while raw := input.read(min(bundle_bytes, max_asset_bytes) if size > max_asset_bytes else size):
                        parts.append(write_blob(staging, raw, "blobs", ".bin")); value.update(raw)
                entries[logical] = {"format": "raw-v1" if len(parts) == 1 else "segments-v1",
                                    "size": size, "sha256": value.hexdigest(), "parts": parts}
            else:
                raw = path.read_bytes()
                cost = 512 + ((len(raw) + 511) // 512) * 512
                if pending and pending_bytes + cost + 10240 > bundle_bytes:
                    flush()
                pending.append((logical, raw)); pending_bytes += cost
        flush()
        if group_number % 500 == 0:
            print(f'Packed {len(entries)}/{len(originals)} source files', file=sys.stderr, flush=True)
    print(f'Verifying all {len(entries)} source files and reconstructed bytes', file=sys.stderr, flush=True)
    verify_roundtrip(staging, entries, originals)
    shards = defaultdict(dict)
    for logical, entry in sorted(entries.items()):
        shards[digest(logical.encode())[:2]][logical] = entry
    indexes = {shard: write_blob(staging, canonical({"schema_version": 1, "entries": values}), "indexes", ".json")
               for shard, values in sorted(shards.items())}
    inventory_hash = digest(canonical({path: {"size": entry["size"], "sha256": entry["sha256"]} for path, entry in sorted(entries.items())}))
    core = {"schema_version": 1, "format": "static-dataset-v1", "publication": publication,
            "source_inventory_sha256": inventory_hash, "source_files": len(entries), "shards": indexes}
    # Retention is part of release identity, so identical current data with a
    # different previous release cannot overwrite an immutable directory.
    old = None
    if previous is not None:
        previous = Path(previous).resolve()
        old = json.loads((previous / 'manifest.json').read_bytes())
        core['retained_revision'] = old['revision']
    revision = digest(canonical(core))
    manifest = {**core, "revision": revision}
    if previous is not None:
        if old["revision"] != revision:
            for relative in referenced_assets(previous, old):
                target = staging / relative
                if target.exists():
                    continue
                raw = (previous / relative).read_bytes()
                if not (previous / relative).resolve().is_relative_to(previous):
                    raise ValueError('Prior asset escapes its release directory')
                if digest(raw) != Path(relative).stem:
                    raise ValueError("Retained asset checksum differs")
                target.parent.mkdir(parents=True, exist_ok=True)
                try:
                    os.link(previous / relative, target)
                except OSError:
                    target.write_bytes(raw)
            manifest["previous"] = write_blob(staging, canonical(old), "manifests", ".json")
    (staging / "manifest.json").write_bytes(canonical(manifest))
    (staging / "_headers").write_text(HEADERS, encoding="utf-8")
    assets = [path for path in staging.rglob("*") if path.is_file()]
    largest = max(path.stat().st_size for path in assets)
    if len(assets) > max_files or largest > max_asset_bytes:
        raise ValueError(f"Free asset limits exceeded: files={len(assets)}, largest={largest}")
    destination = output / "releases" / revision
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        staged = {path.relative_to(staging).as_posix(): digest(path.read_bytes()) for path in assets}
        existing = {path.relative_to(destination).as_posix(): digest(path.read_bytes()) for path in destination.rglob('*') if path.is_file()}
        if staged != existing:
            raise ValueError("Existing immutable release differs")
        # Keep staging for inspection instead of recursively deleting a tree.
    else:
        assert staging.resolve().is_relative_to(output) and destination.resolve().is_relative_to(output)
        staging.replace(destination)
    report = {"revision": revision, "ready_directory": str(destination), "source_files": len(entries),
              "source_bytes": sum(row[2] for row in originals), "source_inventory_sha256": inventory_hash,
              "output_files": len(assets), "output_bytes": sum(path.stat().st_size for path in destination.rglob("*") if path.is_file()),
              "largest_asset_bytes": largest, "roundtrip_verified": True, "limits": {"files": max_files, "asset_bytes": max_asset_bytes}}
    report['publication_evidence_verified'] = evidence_verified
    (output / "reports").mkdir(exist_ok=True)
    (output / "reports" / f"{revision}.json").write_bytes(canonical(report))
    pointer = output / "active.json.tmp"
    pointer.write_bytes(canonical({"revision": revision, "ready_directory": str(destination)})); pointer.replace(output / "active.json")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--publication", type=Path, default=ROOT / "shared/published-history.json")
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--publication-proof", type=Path)
    args = parser.parse_args()
    print(json.dumps(package(args.source, args.output, publication=json.loads(args.publication.read_bytes()), previous=args.previous,
                             publication_proof=args.publication_proof, require_evidence=True)))


if __name__ == "__main__":
    main()
