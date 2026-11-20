"""Bootstrap verified menu boundaries from an existing successful deployment receipt."""
import argparse
import hashlib
import json
from pathlib import Path
from datetime import date, datetime, timedelta, timezone

COUNTS = {"stock_history": "continuous_stock_histories", "financials": "information_snapshots",
          "investors": "investors", "credit": "credit", "sectors": "lossless_sector_archives",
          "new_highs": "new-highs", "turnover": "turnover", "rebounds": "rebound_sessions"}


def from_deployment(raw, evidence_path):
    value = json.loads(raw)
    if (value.get("status") != "complete" or value.get("workflow", {}).get("conclusion") != "success"
            or value.get("api", {}).get("verified") is not True
            or not value.get("production_checks")
            or any(check.get("exit_code") != 0 for check in value["production_checks"].values())):
        raise ValueError("Only a completed, verified deployment receipt can bootstrap published choices")
    start = date.fromisoformat(value["coverage"]["start"])
    verified = date.fromisoformat(value["verified_at"][:10])
    verified_time = datetime.fromisoformat(value["verified_at"].replace("Z", "+00:00"))
    if verified_time.tzinfo is None or verified_time > datetime.now(timezone.utc) + timedelta(minutes=1):
        raise ValueError("Publication proof must have an actual completed verification time")
    sha = hashlib.sha256(raw).hexdigest()
    return {"schema_version": 1, "revision": f"legacy-{sha}",
            "evidence": {"path": evidence_path, "sha256": sha, "commit": value["commit"], "verified_at": value["verified_at"],
                         "basis": "Existing verified deployment; per-listing source limitations remain in the original audits"},
            "kinds": {kind: {"selection_start_year": start.year, "selection_end_year": verified.year - 1,
                              "scope": "observed_with_listing_exceptions", "published_items": value["publication"][key]}
                      for kind, key in COUNTS.items() if value["publication"].get(key, 0) > 0}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proof", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    value = from_deployment(args.proof.read_bytes(), args.proof.as_posix())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
