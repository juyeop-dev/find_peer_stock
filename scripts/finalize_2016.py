"""Finish dependent source jobs after successful collectors; never deploy."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "data/tmp_2016"
PY = [sys.executable, "-u"]
MARKETS = ["korea", "us", "japan", "china", "taiwan", "europe"]


def wait_job(name):
    path = STATE / f"{name}.process.json"
    while True:
        try:
            value = json.loads(path.read_bytes())
        except (FileNotFoundError, ValueError):
            time.sleep(2)
            continue
        if "exit_code" in value:
            if value["exit_code"]:
                raise RuntimeError(f"Dependency {name} failed: see {STATE / (name + '.log')}")
            return
        time.sleep(2)


def run(stage, commands):
    path = STATE / f"stage-{stage}.json"
    if path.exists() and json.loads(path.read_bytes()).get("status") == "complete":
        return
    value = {"status": "running", "started_at": datetime.now(timezone.utc).isoformat(), "commands": commands}
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")
    try:
        with (STATE / f"stage-{stage}.log").open("ab", buffering=0) as output:
            for command in commands:
                subprocess.run(command, cwd=ROOT, stdout=output, stderr=subprocess.STDOUT, check=True)
        value["status"] = "complete"
    except Exception as error:
        value.update(status="failed", error=str(error))
        raise
    finally:
        value["finished_at"] = datetime.now(timezone.utc).isoformat()
        path.write_text(json.dumps(value, indent=2), encoding="utf-8")


def europe():
    wait_job("europe")
    run("europe-turnover", [[*PY, "scripts/run_2016.py", "europe-turnover"]])


def korea():
    wait_job("korea")
    wait_job("source")
    run("korea-finalize", [[*PY, "scripts/finalize_korea_2016.py"]])


def taiwan():
    wait_job("taiwan")
    wait_job("taiwan-bases")
    run("taiwan-gap", [[*PY, "scripts/run_2016.py", "taiwan-gap"]])


def financial():
    for name in [*MARKETS, "financials", "sec"]:
        wait_job(name)
    run("financial-finalize", [[*PY, "scripts/finalize_financials_2016.py"]])


def main():
    with ThreadPoolExecutor(max_workers=4) as pool:
        tasks = [pool.submit(function) for function in [europe, korea, taiwan, financial]]
        for name in [*MARKETS, "history", "semiconductor", "credit", "investors", "rebounds", "replay"]:
            wait_job(name)
        for task in tasks:
            task.result()
    wait_job("japan-gap")
    run("financial-complete", [[*PY, "scripts/finalize_financials_2016.py"]])
    run("histories", [
        [*PY, "scripts/extend_stock_history_2016.py"],
        [*PY, "scripts/refresh_stock_information_history.py", "--state-dir", "data/tmp_2016_history", "--import-chart-cache", "--extend-to-start"],
        [*PY, "scripts/complete_history_audit_2016.py"],
        [*PY, "scripts/import_taiwan_official_histories_2016.py"],
        [*PY, "scripts/exclude_closed_price_observations_2016.py"],
    ])
    run("japan-quality", [
        [*PY, "scripts/repair_japan_adjacent_returns_2016.py"],
        [*PY, "scripts/import_japan_recovered_2016.py", "--no-export"],
        [*PY, "scripts/backfill_stock_information_2016.py", "collect", "--workers", "6", "--market", "japan"],
        [*PY, "scripts/backfill_stock_information_2016.py", "export"],
        [*PY, "scripts/complete_history_audit_2016.py", "--no-export"],
        [*PY, "scripts/exclude_closed_price_observations_2016.py"],
    ])
    wait_job("daily-frequency")
    frequency_stage = STATE / "stage-daily-frequency-finalize.json"
    needs_audit = not frequency_stage.exists() or json.loads(frequency_stage.read_bytes()).get("status") != "complete"
    if needs_audit and (STATE / "stage-audits.json").exists():
        value = json.loads((STATE / "stage-audits.json").read_bytes())
        value.update(status="pending", reason="Reaudit corrected daily-frequency sources")
        (STATE / "stage-audits.json").write_text(json.dumps(value, indent=2), encoding="utf-8")
    run("daily-frequency-finalize", [[*PY, "scripts/exclude_closed_price_observations_2016.py"]])
    run("audits", [
        [*PY, "scripts/audit_japan_quality_2016.py"],
        [*PY, "scripts/prune_closed_sessions_2016.py"],
        [*PY, "scripts/checkpoint_2016.py"],
        [*PY, "scripts/audit_calendar_2016.py"],
        [*PY, "scripts/audit_stock_information_2016.py"],
        [*PY, "scripts/audit_preservation_2016.py"],
    ])
    print("2016 source collection, finalization and preservation audits passed", flush=True)


if __name__ == "__main__":
    main()
