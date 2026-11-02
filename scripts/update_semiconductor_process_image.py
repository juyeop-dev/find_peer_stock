"""Apply the reviewed process map without recollecting existing company histories."""
from __future__ import annotations

import copy
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import generate_semiconductor_data as semis

REVIEW = semis.ROOT / "data/semiconductor/reviews/2026-11-02-process-image.json"
CACHE = semis.ROOT / "data/tmp_semiconductor_process"
METADATA = ("name", "aliases", "business_summary", "business_sources", "major", "middle", "minor", "classifications")


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def reclassify(existing: dict, seeds: list[dict], additions: dict[str, dict]) -> dict:
    """Only replace classification/business metadata on existing observations."""
    prior = {row["ticker"]: row for row in existing["stocks"]}
    rows = []
    for seed in seeds:
        ticker = seed["ticker"]
        row = copy.deepcopy(prior.get(ticker) or additions[ticker])
        for key in METADATA:
            if key in seed:
                row[key] = copy.deepcopy(seed[key])
        rows.append(row)
    return {**existing, "stocks": rows}


def collect(seed: dict) -> dict:
    path = CACHE / "new-companies" / (seed["ticker"] + ".json")
    if path.exists():
        row = json.loads(path.read_text(encoding="utf-8"))
    else:
        row = semis.collect_full_entry(seed, None)
        quote = semis.fetch_current_quote(row["code"])
        row["quote"] = {key: value for key, value in quote.items() if key not in {"name", "market"}}
        row["quote"].update(status="ok", fetched_at=datetime.now(semis.KST).isoformat(), source="Naver Finance")
        semis.write_json(path, row)
    if len(row.get("history", [])) < 250 or not row.get("annual_financials") or not row.get("quarterly_financials"):
        raise ValueError(f"Incomplete new company data: {seed['ticker']}: {row.get('data_errors')}")
    if row["history"][0]["date"] > "2018-01-10":
        raise ValueError(f"2018 prices missing for {seed['ticker']}")
    print(f"Collected {seed['ticker']}: {len(row['history'])} prices; {row['history'][0]['date']}", flush=True)
    return row


def main() -> None:
    review = json.loads(REVIEW.read_text(encoding="utf-8"))
    assert review["status"] == "reviewed"
    CACHE.mkdir(parents=True, exist_ok=True)
    baseline_path = CACHE / "baseline-source.json"
    public_path = CACHE / "baseline-public.json"
    if not baseline_path.exists():
        baseline_path.write_bytes(semis.SOURCE.read_bytes())
        public_path.write_bytes(semis.PUBLISHED.read_bytes())
        (CACHE / "baseline-seeds.json").write_bytes(semis.SEED.read_bytes())
        (CACHE / "baseline-categories.json").write_bytes(semis.CATEGORIES.read_bytes())
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    seeds = json.loads((CACHE / "baseline-seeds.json").read_text(encoding="utf-8"))
    categories = json.loads((CACHE / "baseline-categories.json").read_text(encoding="utf-8"))
    by_ticker = {seed["ticker"]: seed for seed in seeds}
    for addition in review["additions"]:
        assert addition["ticker"] not in by_ticker
        seed = {key: addition[key] for key in ("ticker", "name", "aliases", "business_summary", "business_sources")}
        seeds.append(seed)
        by_ticker[seed["ticker"]] = seed
        for minor in addition["broad_categories"]:
            group = next(group for group in categories if group["minor"] == minor)
            group["additional"].append(seed["ticker"])
    for change in review["name_changes"]:
        seed = by_ticker[change["ticker"]]
        seed["aliases"] = list(dict.fromkeys([*seed.get("aliases", []), change["original"]]))
    for update in review.get("business_updates", []):
        by_ticker[update["ticker"]].update({key: value for key, value in update.items() if key != "ticker"})
    for process in review["processes"]:
        categories.append({"major": process.get("major", "전공정 소부장"), "middle": process["middle"],
                           "minor": process["minor"], "image": [], "additional": process["members"],
                           "source": "2026-11-02-process-image"})
    for path, value in ((semis.SEED, seeds), (semis.CATEGORIES, categories)):
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    classified = semis.classified_seeds()
    old_tickers = {row["ticker"] for row in baseline["stocks"]}
    new_seeds = [seed for seed in classified if seed["ticker"] not in old_tickers]
    with ThreadPoolExecutor(max_workers=4) as pool:
        additions = {row["ticker"]: row for row in pool.map(collect, new_seeds)}
    payload = reclassify(baseline, classified, additions)
    payload.update(seed_hash=semis.seed_fingerprint(), classification_review=semis.process_review_summary(),
                   categories=[{key: group[key] for key in ("major", "middle", "minor")} for group in categories])
    # Quote/financial/history timestamps on old rows remain exactly as collected.
    public = reclassify(json.loads(public_path.read_text(encoding="utf-8")), classified, additions)
    public.update({key: payload[key] for key in ("seed_hash", "classification_review", "categories")})
    for row in public["stocks"]:
        row.pop("prior_history_snapshots", None)
    old_rows = {row["ticker"]: row for row in baseline["stocks"]}
    for row in payload["stocks"]:
        if row["ticker"] in old_rows:
            original = old_rows[row["ticker"]]
            assert {k: v for k, v in row.items() if k not in METADATA} == {k: v for k, v in original.items() if k not in METADATA}
    semis.write_json(semis.SOURCE, payload)
    semis.write_json(semis.PUBLISHED, public)
    audit = {"reviewed_at": review["reviewed_at"], "existing_companies_preserved": len(old_rows),
             "added_companies": len(additions), "total_companies": len(payload["stocks"]),
             "process_groups": len(review["processes"]), "total_groups": len(categories),
             "existing_observations_sha256": digest([{k: v for k, v in row.items() if k not in METADATA} for row in baseline["stocks"]]),
             "new_companies": [{"ticker": row["ticker"], "first_price": row["history"][0]["date"],
                                "prices": len(row["history"]), "errors": row["data_errors"]} for row in additions.values()]}
    semis.write_json(CACHE / "audit.json", audit)
    print(json.dumps(audit, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
