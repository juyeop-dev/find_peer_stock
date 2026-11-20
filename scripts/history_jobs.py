"""Scope-aware resumable job execution with exclusive resource and process leases."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid
from collection_request import collection_request

ROOT = Path(__file__).resolve().parents[1]


def write_record(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def process_alive(pid):
    if type(pid) is not int or pid <= 0:
        raise ValueError("Invalid process lease owner")
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x100000, False, pid)
        if not handle:
            return ctypes.get_last_error() != 87  # Access denied/unknown remains locked.
        try:
            return kernel.WaitForSingleObject(handle, 0) != 0
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def acquire(path, owner):
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as output:
            json.dump(owner, output)
    except FileExistsError:
        guard = path.with_suffix(path.suffix + ".reclaim")
        with guard.open("x"):
            pass
        try:
            previous = json.loads(path.read_text(encoding="utf-8"))
            if process_alive(previous["pid"]) or (previous.get("child_pid") and process_alive(previous["child_pid"])):
                raise FileExistsError(f"Collector already running; lease: {path}")
            path.unlink()
            with path.open("x", encoding="utf-8") as output:
                json.dump(owner, output)
        finally:
            guard.unlink()


def run_job(name, command, *, state, root=ROOT, dependencies=(), identity=None, resource=None):
    if not re.fullmatch(r"[a-z0-9-]+", name):
        raise ValueError("Invalid job name")
    aliases = {"history": "stock-history", "extend": "stock-history", "history-audit": "stock-history",
               "financials": "stock-information", "sec": "stock-information", "financial-finalize": "stock-information",
               "financial-export": "stock-information", "information-audit": ("stock-information", "stock-history"),
               "source": "sectors", "korea-finalize": "sectors", "korea-amounts": "sectors"}
    resource = resource or aliases.get(name, name)
    resources = [resource] if isinstance(resource, str) else list(resource)
    if not resources or not all(re.fullmatch(r"[a-z0-9-]+", value) for value in resources):
        raise ValueError("Invalid resource name")
    state, root = Path(state), Path(root)
    state.mkdir(parents=True, exist_ok=True)
    record = state / f"{name}.process.json"
    lease = {"pid": os.getpid(), "nonce": uuid.uuid4().hex}
    locks = [root / "data/tmp_history_jobs/locks" / f"{value}.lock" for value in sorted(set(resources))]
    locks.append(state / f"{name}.lock")
    acquired = []
    child, child_finished = None, False
    value = {**lease, "command": command, "identity": identity,
             "command_sha256": hashlib.sha256(json.dumps(command).encode()).hexdigest(),
             "started_at": datetime.now(timezone.utc).isoformat()}
    if record.exists():
        value["previous_attempt"] = {k: v for k, v in json.loads(record.read_bytes()).items() if k != "previous_attempt"}
    try:
        for lock in locks:
            acquire(lock, lease); acquired.append(lock)
        write_record(record, value)
        for dependency in dependencies:
            path = state / f"{dependency}.process.json"
            previous = json.loads(path.read_bytes()) if path.exists() else {}
            if previous.get("exit_code") != 0 or (identity is not None and previous.get("identity") != identity):
                raise RuntimeError(f"Dependency {dependency} is not complete for this range; inspect {path}")
        env = {**os.environ, "PYTHONIOENCODING": "utf-8",
               "PYTHONPATH": os.pathsep.join(filter(None, [str(root / "data/tmp_info_update/deps"), os.environ.get("PYTHONPATH")]))}
        options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
        with (state / f"{name}.log").open("ab", buffering=0) as output:
            child = subprocess.Popen(command, cwd=root, stdout=output, stderr=subprocess.STDOUT, env=env, **options)
            lease["child_pid"] = child.pid
            for lock in acquired:
                write_record(lock, lease)
            value["child_pid"] = child.pid
            write_record(record, value)
            code = child.wait()
        child_finished = True
        value.update(exit_code=code, finished_at=datetime.now(timezone.utc).isoformat())
        write_record(record, value)
        return code
    except BaseException as error:
        # If acquiring an existing live lease failed, its owner keeps its receipt.
        if len(acquired) == len(locks):
            value.update(exit_code=130 if isinstance(error, KeyboardInterrupt) else 1,
                         error=f"{type(error).__name__}: {error}", finished_at=datetime.now(timezone.utc).isoformat())
            write_record(record, value)
        raise
    finally:
        child_running = child is not None and not child_finished and child.poll() is None
        if not child_running:
            for lock in reversed(acquired):
                if lock.exists() and json.loads(lock.read_bytes()) == lease:
                    lock.unlink()


def legacy_main(jobs, *, year, argv=None, root=ROOT, dependencies=None):
    parser = argparse.ArgumentParser(description="Run existing historical jobs with resumable leases")
    parser.add_argument("jobs", nargs="+", choices=list(jobs))
    parser.add_argument("--plan", action="store_true")
    args = parser.parse_args(argv)
    request = collection_request(year=year, root=root)
    identity = {"start": request.start, "end": request.end, "reference_start": request.reference_start}
    if args.plan:
        print(json.dumps({"range": identity, "state": str(request.state),
                          "jobs": {name: jobs[name] for name in args.jobs}})); return
    for name in args.jobs:
        code = run_job(name, jobs[name], state=request.state, root=root,
                       dependencies=(dependencies or {}).get(name, ()))
        print(f"{name}: exit={code}", flush=True)
        if code:
            raise SystemExit(code)
