"""Finish 2018 curves after all original chart collection has stopped."""
import subprocess
import sys

for arguments in [
    ['scripts/import_taiwan_official_histories_2018.py'],
    ['scripts/exclude_closed_price_observations_2018.py'],
]:
    subprocess.run([sys.executable, '-u', *arguments], check=True)
