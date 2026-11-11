import subprocess,sys
for arguments in [
    ['scripts/backfill_sector_history_2017.py'],
    ['scripts/recalculate_korea_history.py','--start','2017-01-01','--end','2017-12-31','--audit-tag','2026-11-11-2017','--apply'],
]:subprocess.run([sys.executable,'-u',*arguments],check=True)
