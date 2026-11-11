"""Dated 2017 exchange holidays, including three official Taiwan Saturdays."""
from datetime import date, timedelta
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EU = "https://www.euronext.com/en/about/media/euronext-press-releases/euronext-announces-calendar-2017"
LSE = "https://www.londonstockexchange.com/equities-trading/business-days"
SIX = "https://www.six-group.com/dam/download/sites/education/preparatory-documentation/trading-module/trading-guide.pdf"
XETR = "https://cashmarket.deutsche-boerse.com/resource/blob/336572/247517da046f56e5b4dae39723f29b00/data/trading-calendar-2017.pdf"
DATES = {
    "korea": "01-27 01-30 03-01 05-01 05-03 05-05 05-09 06-06 08-15 10-02 10-03 10-04 10-05 10-06 10-09 12-25 12-29",
    "us": "01-02 01-16 02-20 04-14 05-29 07-04 09-04 11-23 12-25",
    "japan": "01-02 01-03 01-09 03-20 05-03 05-04 05-05 07-17 08-11 09-18 10-09 11-03 11-23",
    "china": "01-02 01-27 01-30 01-31 02-01 02-02 04-03 04-04 05-01 05-29 05-30 10-02 10-03 10-04 10-05 10-06",
    "taiwan": "01-02 01-25 01-26 01-27 01-30 01-31 02-01 02-27 02-28 04-03 04-04 05-01 05-29 05-30 10-04 10-09 10-10",
    # Union of the four supported venues: a day closed in all venues is closed.
    "europe": "04-14 04-17 05-01 12-25 12-26",
}
SOURCES = {
    "korea": ["https://www.krx.co.kr/res/pc/banner/2017marketinfo_en.pdf", "https://github.com/FinanceData/marcap"],
    "us": ["https://www.nasdaq.net/PublicPages/assets/MyMID/2017_Trade_Calendar.pdf"],
    "japan": ["https://www8.cao.go.jp/chosei/shukujitsu/syukujitsu.csv", "https://www.jpx.co.jp/english/corporate/about-jpx/calendar/"],
    "china": ["https://www.sse.com.cn/disclosure/announcement/general/c/c_20161222_4218613.shtml"],
    "taiwan": ["https://www.tpex.org.tw/storage/en-us/web/bulletin/trading_date/trading_date_106.htm"],
    "europe": [EU, LSE, SIX, XETR],
}


def dates(text):
    return {f"2017-{stamp}": "Exchange scheduled non-trading day" for stamp in text.split()}


def main():
    markets = [{"market": key, "source_urls": SOURCES[key], "dates": dates(value)} for key, value in DATES.items()]
    next(row for row in markets if row["market"] == "taiwan")["additional_open_dates"] = {
        "2017-02-18": "Official Saturday make-up trading session",
        "2017-06-03": "Official Saturday make-up trading session",
        "2017-09-30": "Official Saturday make-up trading session",
    }
    path = ROOT / "data/market-closures/2017.json"
    path.write_text(json.dumps({"schema_version": 1, "year": 2017, "markets": markets}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    common = DATES["europe"]
    exchanges = {
        "EURONEXT": (common, EU),
        "LSE": (common + " 01-02 05-29 08-28", LSE),
        "SIX": (common + " 01-02 05-25 06-05 08-01", SIX),
        "XETR": (common + " 06-05 10-03 10-31", XETR),
    }
    path = ROOT / "data/new-highs/europe-exchange-closures.json"
    value = json.loads(path.read_bytes())
    retained = [row for row in value["closures"] if not row["date"].startswith("2017-")]
    for exchange, (stamps, url) in exchanges.items():
        retained.extend({"date": stamp, "exchange": exchange, "reason": reason, "source_url": url} for stamp, reason in dates(stamps).items())
    value["closures"] = sorted(retained, key=lambda row: (row["date"], row["exchange"]))
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    weekdays = {(date(2017, 1, 1) + timedelta(days=i)).isoformat() for i in range(365) if (date(2017, 1, 1) + timedelta(days=i)).weekday() < 5}
    print({row["market"]: len((weekdays | set(row.get("additional_open_dates", {}))) - set(row["dates"])) for row in markets})


if __name__ == "__main__":
    main()
