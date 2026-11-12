import subprocess,sys
for arguments in [
    ['scripts/backfill_sector_history_2016.py'],
    ['scripts/recalculate_korea_history.py','--start','2016-01-01','--end','2016-12-31','--audit-tag','2026-11-12-2016','--apply'],
]:subprocess.run([sys.executable,'-u',*arguments],check=True)
