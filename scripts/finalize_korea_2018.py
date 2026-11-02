import subprocess,sys
for arguments in [
    ['scripts/backfill_sector_history_2018.py'],
    ['scripts/recalculate_korea_history.py','--start','2018-01-01','--end','2018-12-31','--audit-tag','2026-11-02-2018','--apply'],
]:subprocess.run([sys.executable,'-u',*arguments],check=True)
