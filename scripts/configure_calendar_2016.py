"""Configure dated 2016 sessions, including Taiwan Saturday and typhoon dates."""
from datetime import date, timedelta
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EU = "https://www.euronext.com/en/about/media/euronext-press-releases/euronext-announces-calendar-2016"
LSE = "https://www.londonstockexchange.com/equities-trading/business-days"
SIX = "https://www.six-group.com/dam/download/sites/education/preparatory-documentation/trading-module/trading-guide.pdf"
XETR = "https://cashmarket.deutsche-boerse.com/resource/blob/259998/85c710e77ed5d595695f5b1d6418eac7/data/trading-calendar-2016.pdf"
DATES = {
    "korea": "01-01 02-08 02-09 02-10 03-01 04-13 05-05 05-06 06-06 08-15 09-14 09-15 09-16 10-03 12-30",
    "us": "01-01 01-18 02-15 03-25 05-30 07-04 09-05 11-24 12-26",
    "japan": "01-01 01-11 02-11 03-21 04-29 05-03 05-04 05-05 07-18 08-11 09-19 09-22 10-10 11-03 11-23 12-23",
    "china": "01-01 02-08 02-09 02-10 02-11 02-12 04-04 05-02 06-09 06-10 09-15 09-16 10-03 10-04 10-05 10-06 10-07",
    "taiwan": "01-01 02-04 02-05 02-08 02-09 02-10 02-11 02-12 02-29 04-04 04-05 05-02 06-09 06-10 07-08 09-15 09-16 09-27 09-28 10-10",
    "europe": "01-01 03-25 03-28 12-26",
}
SOURCES = {
    "korea": ["https://github.com/FinanceData/marcap"],
    "us": ["https://www.nasdaq.net/PublicPages/assets/MyMID/2016_Trade_Calendar.pdf"],
    "japan": ["https://www8.cao.go.jp/chosei/shukujitsu/syukujitsu.csv", "https://www.jpx.co.jp/english/corporate/about-jpx/calendar/"],
    "china": ["https://www.sse.com.cn/disclosure/dealinstruc/closed/list/c/c_20160104_4028872.shtml"],
    "taiwan": ["https://www.tpex.org.tw/storage/en-us/web/bulletin/trading_date/trading_date_105.htm",
               "https://wwwc.twse.com.tw/en/clearing/suspended.html"],
    "europe": [EU, LSE, SIX, XETR],
}


def dates(text):
    return {f"2016-{stamp}": "Exchange non-trading day" for stamp in text.split()}


def main():
    markets = [{"market": key, "source_urls": SOURCES[key], "dates": dates(value)} for key, value in DATES.items()]
    taiwan = next(row for row in markets if row["market"] == "taiwan")
    taiwan["additional_open_dates"] = {day: "Official Saturday make-up trading session"
        for day in ["2016-01-30", "2016-06-04", "2016-09-10"]}
    for day in ["2016-07-08", "2016-09-27", "2016-09-28"]:
        taiwan["dates"][day] = "Typhoon market closure; verify against actual TWSE/TPEx originals"
    path = ROOT / "data/market-closures/2016.json"
    path.write_text(json.dumps({"schema_version": 1, "year": 2016, "markets": markets}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    common = DATES["europe"]
    exchanges = {"EURONEXT": (common, EU), "LSE": (common + " 05-02 05-30 08-29 12-27", LSE),
        "SIX": (common + " 05-05 05-16 08-01", SIX), "XETR": (common + " 05-16 10-03", XETR)}
    path = ROOT / "data/new-highs/europe-exchange-closures.json"
    value = json.loads(path.read_bytes())
    retained = [row for row in value["closures"] if not row["date"].startswith("2016-")]
    for exchange, (stamps, url) in exchanges.items():
        retained.extend({"date": stamp, "exchange": exchange, "reason": reason, "source_url": url} for stamp, reason in dates(stamps).items())
    value["closures"] = sorted(retained, key=lambda row: (row["date"], row["exchange"]))
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    weekdays = {(date(2016, 1, 1) + timedelta(days=i)).isoformat() for i in range(366) if (date(2016, 1, 1) + timedelta(days=i)).weekday() < 5}
    print({row["market"]: len((weekdays | set(row.get("additional_open_dates", {}))) - set(row["dates"])) for row in markets})


if __name__ == "__main__":
    main()
