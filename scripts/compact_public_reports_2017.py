"""Losslessly compact completed July-October reports to fit the expanded archive."""
import gzip
import hashlib
import json

from archive_paths import publish_daily_report, publish_compressed_bytes
from stock_chart_history import ROOT, write_json


def main():
    public = ROOT / "frontend/public/data"
    proofs = []
    for namespace in ["new-highs", "turnover"]:
        for path in (public / namespace).rglob("2026-*.json"):
            if not "2026-07-01" <= path.stem < "2026-11-01":
                continue
            raw = path.read_bytes()
            value = json.loads(raw)
            publish_daily_report(path, value, public)
            encoded = path.with_suffix(".json.gz").read_bytes()
            assert gzip.decompress(encoded) == raw, path
            proofs.append({"path": path.relative_to(public).as_posix(), "original_sha256": hashlib.sha256(raw).hexdigest(),
                           "original_bytes": len(raw), "compressed_bytes": len(encoded)})
        for path in (public / namespace / "history").rglob("*.json"):
            if not path.stem.isdecimal() or len(path.stem) != 4:
                continue
            raw = path.read_bytes()
            publish_compressed_bytes(path, raw, public)
            encoded = path.with_suffix(".json.gz").read_bytes()
            assert gzip.decompress(encoded) == raw, path
            proofs.append({"path": path.relative_to(public).as_posix(), "original_sha256": hashlib.sha256(raw).hexdigest(),
                           "original_bytes": len(raw), "compressed_bytes": len(encoded)})
    prior = ROOT / "data/information-audit/2017/public-report-compaction.json"
    if prior.exists():
        known = {row["path"]: row for row in json.loads(prior.read_bytes())["reports"]}
        known.update({row["path"]: row for row in proofs})
        proofs = list(known.values())
    result = {"before": "2026-11-01", "verified_reports": len(proofs),
              "saved_bytes": sum(row["original_bytes"] - row["compressed_bytes"] for row in proofs), "reports": proofs}
    write_json(ROOT / "data/information-audit/2017/public-report-compaction.json", result)
    print(f"Losslessly compacted {len(proofs)} reports, saved {result['saved_bytes'] / 1024**2:.2f} MiB")


if __name__ == "__main__":
    main()
