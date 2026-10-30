import subprocess,sys
for arguments in [
    ['scripts/import_recovered_histories_2019.py'],
    ['scripts/refresh_stock_information_history.py','--state-dir','data/tmp_2019_history','--import-europe-cache'],
    ['scripts/refresh_stock_information_history.py','--state-dir','data/tmp_2019_history','--extend-to-start'],
]:subprocess.run([sys.executable,'-u',*arguments],check=True)
