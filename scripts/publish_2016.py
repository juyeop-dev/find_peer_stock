"""Build local public 2016 data while preserving existing current quote snapshots."""
import argparse
import json
import subprocess
import sys

import stock_chart_history as charts
import stock_information as info


def publish_calendars():
    for name in ["generate_new_high_data.py", "generate_turnover_data.py", "generate_calendar_stock_data.py"]:
        subprocess.run([sys.executable, "scripts/" + name], check=True)
    subprocess.run([sys.executable, "scripts/rebound_data.py", "publish"], check=True)
    for name in ["refresh_sectors.mjs", "refresh_investors.mjs"]:
        subprocess.run(["node", "scripts/" + name, "publish"], check=True)


def publish_details():
    charts.publish()
    info.sync_primary_snapshots = lambda values: None
    info.publish()
    source = json.loads((charts.ROOT / "data/semiconductor/index.json").read_bytes())
    path = charts.ROOT / "frontend/public/data/semiconductor/index.json"
    current = json.loads(path.read_bytes())
    histories = {row["ticker"]: row for row in source["stocks"]}
    for stock in current["stocks"]:
        value = histories[stock["ticker"]]
        previous = stock.get("history", [])
        curves = [value["history"], *[snapshot["history"] for snapshot in value.get("prior_history_snapshots", [])]]
        available = {json.dumps(point, sort_keys=True) for curve in curves for point in curve}
        if any(json.dumps(point, sort_keys=True) not in available for point in previous):
            charts.write_json(charts.ROOT / f"data/tmp_2016/public-semiconductor-preservation/{stock['ticker']}.json", {
                "ticker": stock["ticker"], "prior_history_snapshots": [{"history": previous,
                    "preservation_reason": "Pre-update public curve retained separately"}]})
        stock.pop("prior_history_snapshots", None)
        stock.update(history=value["history"], historical_2016_extension=value["historical_2016_extension"])
    charts.write_json(path, current)
    print("Published local 2016 data; existing current quote and peer snapshots preserved", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=["all", "calendars", "details"], default="all")
    args = parser.parse_args()
    if args.phase != "details":
        publish_calendars()
    if args.phase != "calendars":
        publish_details()


if __name__ == "__main__":
    main()
