"""Plan historical collection from policy; execution is opt-in and calendar-gated."""
import argparse
from dataclasses import asdict
from datetime import date
import json
import hashlib
from pathlib import Path
import sys
from collection_request import collection_request, ROOT
from history_policy import DEFAULT_POLICY
from historical_sessions import verified_sessions, verified_european_closures
from history_jobs import run_job
from fetch_korea_source import source_spec, SOURCE_CONFIG


def build_plan(request, *, config=DEFAULT_POLICY, root=ROOT):
    root = Path(root)
    python = [sys.executable, "-u"]
    result = []
    for year in range(int(request.start[:4]), int(request.end[:4]) + 1):
        start, end = f"{year:04d}-01-01", min(f"{year:04d}-12-31", request.end)
        flags = ["--history-config", str(Path(config).resolve()), "--year", str(year)]
        dates = ["--start", start, "--end", end]
        for name, script, extra, markets, dependencies in [
            ("financials", "backfill_stock_information.py", ["collect", "--workers", "12"], [], []),
            ("credit", "backfill_credit.py", [], [], []),
            ("investors", "backfill_investors.mjs", [], ["korea"], []),
            ("sectors", "backfill_sector_history.py", [], ["korea"], ["korea"]),
            ("semiconductor", "backfill_semiconductor_history.py", [], [], []),
            ("replay", "backfill_chart_replay.py", [], ["korea"], ["investors"]),
            ("financial-export", "backfill_stock_information.py", ["export"], [], ["financials"]),
            ("history", "refresh_stock_information_history.py", ["--state-dir", f"data/tmp_{year}_history", "--import-chart-cache", "--extend-to-start"], [], ["korea", "us", "japan", "china", "taiwan", "europe", "financial-export"]),
            ("extend", f"extend_stock_history_{year}.py" if 2014 <= year <= 2023 else "extend_stock_history_2023.py", ["--state-dir", f"data/tmp_{year}_history"], [], ["history"]),
            ("information-audit", "audit_stock_information.py", [], [], ["financial-export", "extend"]),
            ("korea-source", "fetch_korea_source.py", [], [], []),
        ]:
            command = (["node"] if script.endswith(".mjs") else python) + [f"scripts/{script}", *extra, *flags]
            result.append({"year": year, "name": name, "command": command, "markets": markets, "dependencies": dependencies})
        for market in ["korea", "us", "japan", "china", "taiwan"]:
            command = ([*python, "scripts/backfill_korean_new_highs.py", *dates, "--skip-existing"] if market == "korea" else
                       [*python, "scripts/backfill_yahoo_calendars.py", "--market", market, *dates])
            result.append({"year": year, "name": market, "command": command, "markets": [market], "dependencies": []})
        bars = min(5000, max(550, ((date.fromisoformat(request.as_of) - date(year, 1, 1)).days * 5 + 6) // 7 + 100))
        for name, script, dependencies in [("europe", "backfill_european_new_highs.py", []),
                                            ("europe-turnover", "backfill_european_turnover.py", ["europe"])]:
            result.append({"year": year, "name": name, "command": [*python, f"scripts/{script}", *dates,
                           "--daily-bars", str(bars), "--partial-history"], "markets": ["europe"], "dependencies": dependencies})
        result.append({"year": year, "name": "rebounds", "command": [*python, "scripts/backfill_rebounds.py", *dates,
                       "--deps-dir", "data/tmp_korea_recalculation/deps"], "markets": ["korea"], "dependencies": ["korea", "korea-source"]})
        result.append({"year": year, "name": "korea-amounts", "command": [*python, "scripts/recalculate_korea_history.py", *dates,
                       "--audit-tag", f"history-range-{year}", "--apply"], "markets": ["korea"], "dependencies": ["sectors", "korea-source"]})
    policy_hash = hashlib.sha256(Path(config).read_bytes()).hexdigest()
    source_hash = hashlib.sha256(SOURCE_CONFIG.read_bytes()).hexdigest()
    for job in result:
        errors = []
        for market in job["markets"]:
            try:
                verified_sessions(f"{job['year']:04d}-01-01", min(f"{job['year']:04d}-12-31", request.end), market, root=root)
            except (ValueError, OSError) as error:
                errors.append(str(error))
        if job["name"].startswith("europe"):
            try:
                verified_european_closures(f"{job['year']:04d}-01-01", min(f"{job['year']:04d}-12-31", request.end), root=root)
            except (ValueError, OSError) as error:
                errors.append(str(error))
        if job["name"] in {"korea-source", "korea-amounts", "rebounds"}:
            try:
                source_spec(job["year"])
            except (ValueError, OSError) as error:
                errors.append(str(error))
        job.update(blocked=errors, state=str(root / f"data/tmp_{job['year']}"),
                   identity={"start": f"{job['year']:04d}-01-01", "end": min(f"{job['year']:04d}-12-31", request.end),
                             "config": str(Path(config).resolve()), "config_sha256": policy_hash,
                             "source_config_sha256": source_hash})
    rank = {"sectors": 2, "replay": 2, "rebounds": 2, "investors": 1, "europe-turnover": 1,
            "financial-export": 1, "history": 2, "extend": 3, "korea-amounts": 3, "information-audit": 4}
    return sorted(result, key=lambda job: (job["year"], rank.get(job["name"], 0)))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history-config", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--year", type=int)
    parser.add_argument("--job")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--rerun-completed", action="store_true", help="Repeat an already successful matching job receipt.")
    args = parser.parse_args(argv)
    try:
        request = collection_request(year=args.year, config=args.history_config)
        jobs = build_plan(request, config=args.history_config)
        if args.job:
            jobs = [job for job in jobs if job["name"] == args.job]
            if not jobs:
                raise ValueError("Unknown historical job")
    except (ValueError, OSError) as error:
        parser.error(str(error))
    if not args.execute:
        print(json.dumps({"request": asdict(request), "jobs": jobs}, default=str)); return
    if any(job["blocked"] for job in jobs):
        parser.error("Verified source/calendar evidence is missing; inspect the plan before execution")
    for job in jobs:
        if hashlib.sha256(args.history_config.read_bytes()).hexdigest() != job["identity"]["config_sha256"]:
            parser.error("Collection policy changed after planning; inspect a new plan before execution")
        if (job["identity"].get("source_config_sha256") is not None and
                hashlib.sha256(SOURCE_CONFIG.read_bytes()).hexdigest() != job["identity"]["source_config_sha256"]):
            parser.error("Approved source registry changed after planning; inspect a new plan before execution")
        receipt_path = Path(job["state"]) / f"{job['name']}.process.json"
        if receipt_path.exists() and not args.rerun_completed:
            receipt = json.loads(receipt_path.read_bytes())
            digest = hashlib.sha256(json.dumps(job["command"]).encode()).hexdigest()
            if receipt.get("exit_code") == 0 and receipt.get("identity") == job["identity"] and receipt.get("command_sha256") == digest:
                continue
        code = run_job(job["name"], job["command"], state=Path(job["state"]),
                       dependencies=job["dependencies"], identity=job["identity"])
        if code:
            raise SystemExit(code)


if __name__ == "__main__":
    main()
