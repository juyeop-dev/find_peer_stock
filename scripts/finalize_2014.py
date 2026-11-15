"""Finish dependent source jobs after successful collectors; never deploy."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import time
import os
import argparse

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "data/tmp_2014"
PY = [sys.executable, "-u"]
MARKETS = ["korea", "us", "japan", "china", "taiwan", "europe"]
RESUME_FAILED_COMMAND = False


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
    previous = json.loads(path.read_bytes()) if path.exists() else {}
    if previous.get("status") == "complete":
        return
    value = {"status": "running", "started_at": datetime.now(timezone.utc).isoformat(), "commands": commands}
    start = 0
    if RESUME_FAILED_COMMAND and previous.get('status') == 'failed' and previous.get('commands') == commands:
        for index, command in enumerate(commands):
            known_error = str(subprocess.CalledProcessError(1, command))
            if previous.get('failed_command') == command or previous.get('error') == known_error:
                start = index
                value.update(resumed_command_index=start, previous_attempt=previous,
                             completed_commands=commands[:start])
                break
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")
    try:
        with (STATE / f"stage-{stage}.log").open("ab", buffering=0) as output:
            for command in commands[start:]:
                try:
                    subprocess.run(command, cwd=ROOT, stdout=output, stderr=subprocess.STDOUT, check=True)
                except Exception:
                    value['failed_command'] = command
                    raise
                value.setdefault('completed_commands', []).append(command)
                path.write_text(json.dumps(value, indent=2), encoding='utf-8')
        value["status"] = "complete"
    except Exception as error:
        value.update(status="failed", error=str(error))
        raise
    finally:
        value["finished_at"] = datetime.now(timezone.utc).isoformat()
        path.write_text(json.dumps(value, indent=2), encoding="utf-8")


def europe():
    wait_job("europe-turnover")


def korea():
    wait_job("korea")
    wait_job("source")
    run("korea-finalize", [[*PY, "scripts/finalize_korea_2014.py"]])


def financial():
    for name in [*MARKETS, "europe-turnover", "taiwan-gap", "financials", "sec"]:
        wait_job(name)
    run("financial-finalize", [[*PY, "scripts/finalize_financials_2014.py"]])


def history():
    for name in [*MARKETS, "europe-turnover", "taiwan-gap"]:
        wait_job(name)
    run("histories", [
        [*PY, "scripts/extend_stock_history_2014.py"],
        [*PY, "scripts/refresh_stock_information_history.py", "--state-dir", "data/tmp_2014_history", "--import-chart-cache", "--extend-to-start"],
        [*PY, "scripts/complete_history_audit_2014.py"],
        [*PY, "scripts/import_taiwan_official_histories_2014.py"],
        [*PY, "scripts/exclude_closed_price_observations_2014.py"],
    ])


def main():
    with ThreadPoolExecutor(max_workers=4) as pool:
        tasks = [pool.submit(function) for function in [europe, korea, financial, history]]
        for name in ["semiconductor", "credit", "investors", "rebounds", "replay"]:
            wait_job(name)
        for task in tasks:
            task.result()
    run("audits", [
        [*PY, "scripts/prune_closed_sessions_2014.py"],
        [*PY, "scripts/checkpoint_2014.py"],
        [*PY, "scripts/audit_calendar_2014.py"],
        [*PY, "scripts/audit_calendar_sources_2014.py"],
        [*PY, "scripts/audit_stock_information_2014.py"],
        [*PY, "scripts/audit_preservation_2014.py"],
    ])
    print("2014 source collection, finalization and preservation audits passed", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--resume-failed-command', action='store_true',
                        help='Resume the exact failed command of an unchanged sequential stage; retain prior completion evidence.')
    RESUME_FAILED_COMMAND = parser.parse_args().resume_failed_command
    lock = STATE / 'coordinator.lock'
    try:
        stream = lock.open('x')
    except FileExistsError:
        print('A 2014 coordinator already owns the dependent writers', flush=True)
        raise SystemExit(0)
    with stream:
        stream.write(str(os.getpid()))
    try:
        main()
    finally:
        lock.unlink(missing_ok=True)
