from pathlib import Path
import subprocess,sys,time
root=Path(__file__).resolve().parents[1]
log=root/'data/tmp_2019/europe.log'
while len(list((root/'data/new-highs/reports/europe').glob('2019-*.json')))<256:
    text=log.read_text(encoding='utf-8',errors='replace') if log.exists() else ''
    if 'Traceback' in text or 'European history recovery failed:' in text:raise RuntimeError(text[-2000:])
    time.sleep(2)
subprocess.run([sys.executable,'-u','scripts/backfill_european_turnover.py','--start','2019-01-01','--end','2019-12-31','--daily-bars','2800','--partial-history'],cwd=root,check=True)
