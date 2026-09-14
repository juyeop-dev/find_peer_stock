"""Update Korean archive display names without recollecting historical prices."""

from __future__ import annotations

import argparse
from pathlib import Path

from generate_new_high_data import SOURCE_DIR, load_markets, read_json, validate_report
from new_high_sources.tradingview import fetch_korean_listing
from refresh_new_highs import atomic_json


def localize_reports(source_dir: Path = SOURCE_DIR, *, fetch_listing=fetch_korean_listing) -> int:
    markets = {market["id"]: market for market in load_markets(source_dir)}
    reports_dir = source_dir / "reports"
    updates = []
    listings = {}
    for path in sorted((reports_dir / "korea").glob("*.json")):
        report = read_json(path)
        validate_report(report, path, reports_dir, markets)
        for entry in report["entries"]:
            code = entry["ticker"].rsplit(".", 1)[0]
            if code not in listings:
                listings[code] = fetch_listing(code)
            listing = listings[code]
            if entry["exchange"] != listing["exchange"]:
                raise ValueError(f"{path}: listing exchange changed for {code}; review manually")
            old_name = entry["name"]
            if old_name != listing["name"]:
                entry.setdefault("name_original", old_name)
                entry["name"] = listing["name"]
                # Preserve authored business descriptions; only replace our generated prefix.
                description = entry.get("description", "")
                if description.startswith(old_name + " · "):
                    entry["description"] = listing["name"] + description[len(old_name):]
            entry["name_source_url"] = listing["source_url"]
        sources = report.setdefault("sources", [])
        if not any(item.get("label") == "Naver Finance 한국 종목명" for item in sources):
            sources.append({"label": "Naver Finance 한국 종목명", "url": "https://stock.naver.com/"})
        validate_report(report, path, reports_dir, markets)
        updates.append((path, report))
    # Resolve and validate every listing first, so a source failure cannot leave
    # an archive partially renamed. Existing price and collection times are kept.
    for path, report in updates:
        atomic_json(path, report)
    return len(updates)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=SOURCE_DIR)
    args = parser.parse_args()
    print(f"Localized {localize_reports(args.source_dir)} Korean daily reports.")
