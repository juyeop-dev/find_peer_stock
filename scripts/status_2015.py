"""Summarize collector checkpoints without treating pending data as complete."""
import json
from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parents[1]


def main():
    state = ROOT / "data/tmp_2015"
    for path in sorted(state.glob("*.process.json")):
        value = json.loads(path.read_bytes())
        status = "running" if "exit_code" not in value else "complete" if value["exit_code"] == 0 else f"FAILED ({value['exit_code']})"
        log = path.with_name(path.name.replace(".process.json", ".log"))
        last = ""
        if log.exists():
            with log.open("rb") as stream:
                stream.seek(max(0, log.stat().st_size - 2048))
                lines = stream.read().decode("utf-8", errors="replace").splitlines()
                last = lines[-1] if lines else ""
        print(f"{path.name.removesuffix('.process.json')}: {status}; {last}")
    for path in sorted(state.glob("stage-*.json")):
        value = json.loads(path.read_bytes())
        print(f"{path.stem}: {value['status']}")
    for folder, table in [("tmp_2015", "financial_2015_updates"), ("tmp_2015_history", "history_2015_updates")]:
        path = ROOT / "data" / folder / "information.sqlite"
        if path.exists():
            try:
                with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=2) as db:
                    count = db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                    print(f"{table}: {count} saved checkpoints")
            except sqlite3.OperationalError as error:
                print(f"{table}: {error}")
    for namespace in ["new-highs", "turnover"]:
        counts = {market: len(list((ROOT / f"data/{namespace}/reports/{market}").rglob("2015-*.json")))
                  for market in ["korea", "us", "japan", "china", "taiwan", "europe"]}
        print(f"{namespace} 2015 reports: {counts}")


if __name__ == "__main__":
    main()
