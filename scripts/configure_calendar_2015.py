"""Configure actual 2015 sessions, including extraordinary market closures."""
from datetime import date, timedelta
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EU = "https://athens.euronext.com/el/documents/10180/2312453/Xnet_holidays_2015_En.pdf/d4ee8f6b-39da-43fc-add6-ba9c2a5bc5ff"
NYSE = "https://ir.theice.com/press/news-details/2013/NYSE-Euronext-Announces-2015-Holiday-Calendar-and-Early-Closings/default.aspx"
TW = "https://www.tpex.org.tw/storage/en-us/web/bulletin/trading_date/trading_date_104.htm"
XETR = "https://www.xetra.com/resource/blob/252786/26a3eefdbb8b939be91ec1d3d1986347/data/trading-calendar-2015.pdf"
DATES = {
    "korea": "01-01 02-18 02-19 02-20 05-01 05-05 05-25 08-14 09-28 09-29 10-09 12-25 12-31",
    "us": "01-01 01-19 02-16 04-03 05-25 07-03 09-07 11-26 12-25",
    "japan": "01-01 01-02 01-12 02-11 04-29 05-04 05-05 05-06 07-20 09-21 09-22 09-23 10-12 11-03 11-23 12-23 12-31",
    "china": "01-01 01-02 02-18 02-19 02-20 02-23 02-24 04-06 05-01 06-22 09-03 09-04 10-01 10-02 10-05 10-06 10-07",
    "taiwan": "01-01 01-02 02-16 02-17 02-18 02-19 02-20 02-23 02-27 04-03 04-06 05-01 06-19 07-10 09-28 09-29 10-09",
    # Combined calendar uses the union of venues; London trades on May 1.
    "europe": "01-01 04-03 04-06 12-25",
}
SOURCES = {
    "korea": ["https://github.com/FinanceData/marcap", "https://www.mofa.go.kr/www/brd/m_4075/view.do?page=160&pitem=10&seq=355899"],
    "us": [NYSE],
    "japan": ["https://www8.cao.go.jp/chosei/shukujitsu/syukujitsu.csv", "https://www.jpx.co.jp/english/corporate/about-jpx/calendar/"],
    "china": ["https://www.sse.com.cn/disclosure/dealinstruc/closed/list/c/c_20160104_3979217.shtml", "https://www.sse.com.cn/disclosure/dealinstruc/closed/list/c/c_20160104_3979337.shtml"],
    "taiwan": [TW, "https://wwwc.twse.com.tw/en/clearing/suspended.html"],
    "europe": [EU, XETR],
}


def dates(text):
    return {f"2015-{stamp}": "Exchange non-trading day" for stamp in text.split()}


def main():
    markets = [{"market": key, "source_urls": SOURCES[key], "dates": dates(value)} for key, value in DATES.items()]
    taiwan = next(row for row in markets if row["market"] == "taiwan")
    for day in ["2015-07-10", "2015-09-29"]:
        taiwan["dates"][day] = "Typhoon market closure; checked against observed TWSE/TPEx originals"
    (ROOT / "data/market-closures/2015.json").write_text(json.dumps({"schema_version": 1, "year": 2015, "markets": markets}, indent=2) + "\n", encoding="utf-8")
    common = DATES["europe"]
    exchanges = {"EURONEXT": (common + " 05-01", EU), "LSE": (common + " 05-04 05-25 08-31 12-28", EU),
        "SIX": (common + " 01-02 05-01 05-14 05-25 12-24 12-31", EU),
        "XETR": (common + " 05-01 05-25 12-24 12-31", XETR)}
    path = ROOT / "data/new-highs/europe-exchange-closures.json"
    value = json.loads(path.read_bytes())
    retained = [row for row in value["closures"] if not row["date"].startswith("2015-")]
    for exchange, (stamps, url) in exchanges.items():
        retained.extend({"date": stamp, "exchange": exchange, "reason": reason, "source_url": url} for stamp, reason in dates(stamps).items())
    value["closures"] = sorted(retained, key=lambda row: (row["date"], row["exchange"]))
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    weekdays = {(date(2015, 1, 1) + timedelta(days=i)).isoformat() for i in range(365) if (date(2015, 1, 1) + timedelta(days=i)).weekday() < 5}
    print({row["market"]: len(weekdays - set(row["dates"])) for row in markets})


if __name__ == "__main__":
    main()
