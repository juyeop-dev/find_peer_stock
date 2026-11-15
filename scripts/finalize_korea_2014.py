import subprocess,sys
for arguments in [
    ['scripts/backfill_sector_history_2014.py'],
    ['scripts/recalculate_korea_history.py','--start','2014-01-01','--end','2014-12-31','--audit-tag','2026-11-13-2014','--apply'],
]:subprocess.run([sys.executable,'-u',*arguments],check=True)
