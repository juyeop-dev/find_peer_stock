import subprocess,sys
for arguments in [
    ['scripts/backfill_sector_history_2015.py'],
    ['scripts/recalculate_korea_history.py','--start','2015-01-01','--end','2015-12-31','--audit-tag','2026-11-13-2015','--apply'],
]:subprocess.run([sys.executable,'-u',*arguments],check=True)
