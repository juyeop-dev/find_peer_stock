import subprocess,sys
import json,time
from pathlib import Path

record = Path('data/tmp_2016/financial-retry.process.json')
while record.exists():
    value = json.loads(record.read_bytes())
    if 'exit_code' in value:
        if value['exit_code']:
            raise RuntimeError('Blocked-network retry failed; inspect financial-retry.log')
        break
    time.sleep(2)

for arguments in [
    ['scripts/backfill_stock_information_2016.py','collect','--workers','12'],
    ['scripts/backfill_sec_financials_2016.py','apply'],
    ['scripts/backfill_stock_information_2016.py','export'],
]:subprocess.run([sys.executable,'-u',*arguments],check=True)
