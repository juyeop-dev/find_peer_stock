import subprocess,sys
for arguments in [
    ['scripts/backfill_stock_information_2019.py','collect','--workers','12'],
    ['scripts/backfill_sec_financials_2019.py','apply'],
    ['scripts/backfill_stock_information_2019.py','export'],
]:subprocess.run([sys.executable,'-u',*arguments],check=True)
