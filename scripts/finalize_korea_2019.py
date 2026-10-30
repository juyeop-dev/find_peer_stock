import subprocess,sys
for arguments in [
    ['scripts/backfill_sector_history_2019.py'],
    ['scripts/recalculate_korea_history.py','--start','2019-01-01','--end','2019-12-31','--audit-tag','2026-10-30-2019','--apply'],
]:subprocess.run([sys.executable,'-u',*arguments],check=True)
