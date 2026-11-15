"""Launch resumable 2014 collectors only after the verified production baseline."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / 'data/tmp_2014'
JOBS = ['financials', 'sec', 'semiconductor', 'replay', 'korea', 'us', 'japan',
        'china', 'taiwan', 'credit', 'investors', 'source', 'europe',
        'europe-turnover', 'rebounds', 'taiwan-bases', 'taiwan-gap']
PROCESSES = []


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError as error:
        if getattr(error, 'winerror', None) == 87:
            return False
        raise


def launch(name, command):
    with (STATE / f'launcher-{name}.log').open('ab', buffering=0) as log:
        flags = (subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP) if os.name == 'nt' else 0
        child = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                                 stdin=subprocess.DEVNULL, close_fds=True, creationflags=flags,
                                 env={**os.environ, 'PYTHONIOENCODING': 'utf-8',
                                      'PYTHONPATH': str(ROOT / 'data/tmp_info_update/deps')})
    PROCESSES.append(child)
    return {'pid': child.pid, 'command': command, 'started_at': datetime.now(timezone.utc).isoformat()}


def main():
    assert (STATE / 'activated.json').exists(), 'Activate the reviewed 2015 production baseline first'
    manifest = STATE / 'launches.json'
    launches = json.loads(manifest.read_bytes()) if manifest.exists() else {}
    for name in JOBS:
        record = STATE / f'{name}.process.json'
        if record.exists():
            value = json.loads(record.read_bytes())
            if value.get('exit_code') == 0 or 'exit_code' not in value and alive(value['pid']):
                print(name, 'preserved existing successful/running job', flush=True)
                continue
        if not record.exists() and name in launches and alive(launches[name]['pid']):
            print(name, 'already launched', flush=True)
            continue
        launches[name] = launch(name, [sys.executable, '-u', 'scripts/run_2014.py', name])
        manifest.write_text(json.dumps(launches, indent=2), encoding='utf-8')
        print(name, launches[name]['pid'], flush=True)
    name = 'coordinator'
    if name not in launches or not alive(launches[name]['pid']):
        launches[name] = launch(name, [sys.executable, '-u', 'scripts/finalize_2014.py'])
        manifest.write_text(json.dumps(launches, indent=2), encoding='utf-8')
        print(name, launches[name]['pid'], flush=True)
    # Keep the owning execution session alive. The managed Windows executor
    # closes orphaned network children when their launcher exits.
    print('Collector supervisor retained until all launched jobs finish', flush=True)
    while any(child.poll() is None for child in PROCESSES):
        time.sleep(2)
    print('All supervised processes exited; inspect status_2014.py for outcomes', flush=True)


if __name__ == '__main__':
    main()
