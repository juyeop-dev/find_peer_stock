"""Fetch only an approved revision-pinned annual KRX mirror; preserve cached originals."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from urllib.request import Request, urlopen
from collection_request import collection_request, ROOT
from history_policy import DEFAULT_POLICY

SOURCE_CONFIG = ROOT / "config/history-sources.json"


def source_spec(year, *, config=SOURCE_CONFIG):
    value = json.loads(Path(config).read_text(encoding="utf-8-sig"))
    if set(value) != {"schema_version", "marcap_revisions"} or value["schema_version"] != 1:
        raise ValueError("Unsupported historical source registry")
    revision = value["marcap_revisions"].get(str(year), "")
    if not re.fullmatch(r"[a-f0-9]{40}", revision):
        raise ValueError(f"No approved pinned KRX source for {year}; verify its original before adding a registry entry")
    return {"year": year, "revision": revision,
            "url": f"https://raw.githubusercontent.com/FinanceData/marcap/{revision}/data/marcap-{year}.parquet"}


def collect(year, *, cache_dir=None, source_config=SOURCE_CONFIG):
    spec = source_spec(year, config=source_config)
    directory = Path(cache_dir) if cache_dir is not None else ROOT / "data/tmp_korea_recalculation/source"
    path = directory / f"marcap-{year}.parquet"
    metadata = path.with_suffix(".source.json")
    if path.exists() or metadata.exists():
        if not path.exists() or not metadata.exists():
            raise ValueError("Cached KRX original and provenance must both exist; preserve and inspect the incomplete pair")
        raw, previous = path.read_bytes(), json.loads(metadata.read_bytes())
        if (any(previous.get(key) != item for key, item in spec.items())
                or hashlib.sha256(raw).hexdigest() != previous.get("sha256")):
            raise ValueError("Cached KRX revision/date/checksum differs; original retained")
        return previous
    with urlopen(Request(spec["url"], headers={"User-Agent": "Stock Study historical research"}), timeout=90) as response:
        raw = response.read()
    if raw[:4] != b"PAR1" or raw[-4:] != b"PAR1":
        raise ValueError("KRX original is not a Parquet file")
    directory.mkdir(parents=True, exist_ok=True)
    value = {**spec, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
             "fetched_at": datetime.now(timezone.utc).isoformat()}
    temporary = path.with_suffix(".parquet.tmp")
    temporary.write_bytes(raw); temporary.replace(path)
    temporary = metadata.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8"); temporary.replace(metadata)
    return value


def main(argv=None, *, year=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, default=year)
    parser.add_argument("--history-config", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--source-config", type=Path, default=SOURCE_CONFIG)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        request = collection_request(year=args.year, config=args.history_config)
        years = range(int(request.start[:4]), int(request.end[:4]) + 1)
        specs = [source_spec(value, config=args.source_config) for value in years]
    except (ValueError, OSError) as error:
        parser.error(str(error))
    if args.dry_run:
        print(json.dumps(specs)); return
    for spec in specs:
        print(json.dumps(collect(spec["year"], source_config=args.source_config)))


if __name__ == "__main__":
    main()
