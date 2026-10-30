import subprocess,sys
for day in ['2019-04-29','2019-04-30']:
    subprocess.run([sys.executable,'-u','scripts/recover_china_calendar_gap_2019.py','--date',day],check=True)
