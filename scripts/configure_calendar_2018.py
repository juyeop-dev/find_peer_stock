"""Document 2018 exchange calendars, including Taiwan's two Saturday sessions."""
from datetime import date, timedelta
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]
EU = 'https://www.euronext.com/en/about/media/euronext-press-releases/euronext-announces-2018-holiday-calendar-its-cash-and'
LSE = 'https://www.londonstockexchange.com/equities-trading/business-days'
SIX = 'https://www.six-group.com/dam/download/sites/education/preparatory-documentation/trading-module/trading-guide.pdf'
XETR = 'https://www.cashmarket.deutsche-boerse.com/cash-en/trading/trading-calendar-and-trading-hours/non-trading-days'
TW = 'https://www.twse.com.tw/staticFiles/product/publication/0001002657.pdf'
DATES = {
    'korea': '01-01 02-15 02-16 03-01 05-01 05-07 05-22 06-06 06-13 08-15 09-24 09-25 09-26 10-03 10-09 12-25 12-31',
    'us': '01-01 01-15 02-19 03-30 05-28 07-04 09-03 11-22 12-05 12-25',
    'japan': '01-01 01-02 01-03 01-08 02-12 03-21 04-30 05-03 05-04 07-16 09-17 09-24 10-08 11-23 12-24 12-31',
    'china': '01-01 02-15 02-16 02-19 02-20 02-21 04-05 04-06 04-30 05-01 06-18 09-24 10-01 10-02 10-03 10-04 10-05 12-31',
    'taiwan': '01-01 02-13 02-14 02-15 02-16 02-19 02-20 02-28 04-04 04-05 04-06 05-01 06-18 09-24 10-10 12-31',
    'europe': '01-01 03-30 04-02 12-25 12-26',
}
SOURCES = {
    'korea': ['https://global.krx.co.kr/contents/GLB/05/0501/0501110000/GLB0501110000.jsp', 'https://github.com/FinanceData/marcap'],
    'us': ['https://www.nasdaqtrader.com/TraderNews.aspx?id=ETA2018-98', 'https://www.nasdaqtrader.com/Trader.aspx?id=Calendar'],
    'japan': ['https://www8.cao.go.jp/chosei/shukujitsu/syukujitsu.csv', 'https://www.jpx.co.jp/english/corporate/about-jpx/calendar/'],
    'china': ['https://www.sse.com.cn/disclosure/announcement/general/c/c_20171222_4438363.shtml', 'https://www.sse.com.cn/disclosure/announcement/general/c/c_20181220_4696473.shtml'],
    'taiwan': [TW, 'https://taiwanindex.com.tw/news/101'],
    'europe': [EU, LSE, SIX, XETR],
}


def dates(text):
    return {f'2018-{stamp}': 'Exchange scheduled non-trading day' for stamp in text.split()}


def main():
    markets = [{'market': key, 'source_urls': SOURCES[key], 'dates': dates(value)} for key, value in DATES.items()]
    taiwan = next(row for row in markets if row['market'] == 'taiwan')
    taiwan['additional_open_dates'] = {'2018-03-31': 'Saturday make-up trading session for April 6', '2018-12-22': 'Saturday make-up trading session for December 31'}
    config = {'schema_version': 1, 'year': 2018, 'markets': markets}
    path = ROOT / 'data/market-closures/2018.json'
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    common = DATES['europe']
    exchanges = {
        'EURONEXT': (common+' 05-01', EU),
        'LSE': (common+' 05-07 05-28 08-27', LSE),
        'SIX': (common+' 01-02 05-01 05-10 05-21 08-01 12-24 12-31', SIX),
        'XETR': (common+' 05-01 05-21 10-03 12-24 12-31', XETR),
    }
    path = ROOT / 'data/new-highs/europe-exchange-closures.json'
    value = json.loads(path.read_bytes())
    retained = [row for row in value['closures'] if not row['date'].startswith('2018-')]
    for exchange, (stamps, url) in exchanges.items():
        retained += [{'date': stamp, 'exchange': exchange, 'reason': reason, 'source_url': url} for stamp, reason in dates(stamps).items()]
    value['closures'] = sorted(retained, key=lambda row: (row['date'], row['exchange']))
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    weekdays = {(date(2018, 1, 1)+timedelta(days=i)).isoformat() for i in range(365) if (date(2018, 1, 1)+timedelta(days=i)).weekday() < 5}
    print({row['market']: len((weekdays | set(row.get('additional_open_dates', {})))-set(row['dates'])) for row in markets})


if __name__ == '__main__':
    main()
