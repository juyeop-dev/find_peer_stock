"""Verify compact public calendar prices and all replaced public observations."""
from datetime import datetime, timezone
import gzip
import hashlib
import json
import math

from stock_chart_history import ROOT, write_json


def main():
    public = ROOT / "frontend/public/data"
    assert not any((public / "calendar-stocks").rglob("*.json")), "Calendar publication is still incomplete"
    backup = ROOT / "data/tmp_published_report_backup"
    prior = {}
    for line in (backup / "manifest.jsonl").read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row["path"].startswith("calendar-stocks/"):
            prior[row["path"]] = row["sha256"]
    files = points = preserved = before = after = 0
    for path in (public / "calendar-stocks").rglob("*.json.gz"):
        raw = gzip.decompress(path.read_bytes())
        value = json.loads(raw)
        assert value["schema_version"] == 1 and value["market"] and value["ticker"], path
        observations = value["history"]
        keys = [(point["date"], point["currency"]) for point in observations]
        assert keys == sorted(set(keys)), path
        assert all(type(point["close"]) in {int, float} and math.isfinite(point["close"]) and point["close"] > 0 for point in observations), path
        name = path.relative_to(public).as_posix().removesuffix(".gz")
        if name in prior:
            original = (backup / f"{prior[name]}.json").read_bytes()
            assert hashlib.sha256(original).hexdigest() == prior[name]
            old = json.loads(original)
            assert (old["market"], old["ticker"]) == (value["market"], value["ticker"])
            current = {(point["date"], point["currency"]): point for point in observations}
            assert all(current.get((point["date"], point["currency"])) == point for point in old["history"]), path
            preserved += len(old["history"])
        assert not path.with_suffix("").exists(), path
        files += 1
        points += len(observations)
        before += len(raw)
        after += path.stat().st_size
    assert files > 20000
    result = {"checked_at": datetime.now(timezone.utc).isoformat(), "files": files, "observations": points,
        "preserved_prior_observations": preserved, "uncompressed_bytes": before, "compressed_bytes": after,
        "saved_bytes": before - after, "original_backup_files": len(prior)}
    write_json(ROOT / "data/information-audit/2015/calendar-price-compaction.json", result)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
