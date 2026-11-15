"""Configure verified 2014 holidays, typhoon closure and Saturday trading."""
from datetime import date, timedelta
import json
from pathlib import Path

from fetch_calendar_sources_2014 import SOURCES

ROOT = Path(__file__).resolve().parents[1]
TAIWAN_SUPPLEMENT = 'https://www.twsa.org.tw/B01/doc/104Q1.pdf'
DATES = {
    'korea': '01-01 01-30 01-31 05-01 05-05 05-06 06-04 06-06 08-15 09-08 09-09 09-10 10-03 10-09 12-25 12-31',
    'us': '01-01 01-20 02-17 04-18 05-26 07-04 09-01 11-27 12-25',
    'japan': '01-01 01-02 01-03 01-13 02-11 03-21 04-29 05-05 05-06 07-21 09-15 09-23 10-13 11-03 11-24 12-23 12-31',
    'china': '01-01 01-31 02-03 02-04 02-05 02-06 04-07 05-01 05-02 06-02 09-08 10-01 10-02 10-03 10-06 10-07',
    'taiwan': '01-01 01-28 01-29 01-30 01-31 02-03 02-04 02-28 04-04 05-01 06-02 07-23 09-08 10-10',
    # Combined venue calendar is the union; London trades on 1 May.
    'europe': '01-01 04-18 04-21 12-25 12-26',
}
URLS = {
    'korea': ['https://github.com/FinanceData/marcap', SOURCES['eurex']],
    'us': [SOURCES['us']], 'japan': [SOURCES['japan-holidays']],
    'china': [SOURCES['china']],
    'taiwan': [SOURCES['taiwan'], TAIWAN_SUPPLEMENT, SOURCES['taiwan-suspended']],
    'europe': [SOURCES['europe'], SOURCES['xetra']],
}


def dates(text):
    return {f'2014-{stamp}': 'Exchange non-trading day' for stamp in text.split()}


def main():
    manifest = json.loads((ROOT / 'data/tmp_2014/sources/manifest.json').read_bytes())
    assert all(manifest[key].get('sha256') for key in ['taiwan', 'us', 'china', 'japan-holidays', 'europe', 'xetra'])
    markets = [{'market': market, 'source_urls': URLS[market], 'dates': dates(text)} for market, text in DATES.items()]
    tw = next(row for row in markets if row['market'] == 'taiwan')
    tw['dates']['2014-07-23'] = 'Typhoon Matmo closure; checked against original TWSE/TPEx sessions'
    tw['additional_open_dates'] = {'2014-12-27': 'Saturday makeup session for 2015-01-02; TWSA 2015 Q1 official bulletin and exchange daily originals'}
    path = ROOT / 'data/market-closures/2014.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'schema_version': 1, 'year': 2014, 'markets': markets}, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    common = DATES['europe']
    exchanges = {
        'EURONEXT': (common + ' 05-01', SOURCES['europe']),
        'LSE': (common + ' 05-05 05-26 08-25', SOURCES['europe']),
        'SIX': (common + ' 01-02 05-01 05-29 06-09 08-01 12-24 12-31', SOURCES['eurex']),
        'XETR': (common + ' 05-01 10-03 12-24 12-31', SOURCES['xetra']),
    }
    path = ROOT / 'data/new-highs/europe-exchange-closures.json'
    value = json.loads(path.read_bytes())
    retained = [row for row in value['closures'] if not row['date'].startswith('2014-')]
    for exchange, (text, url) in exchanges.items():
        retained.extend({'date': day, 'exchange': exchange, 'reason': reason, 'source_url': url} for day, reason in dates(text).items())
    value['closures'] = sorted(retained, key=lambda row: (row['date'], row['exchange']))
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    weekdays = {(date(2014, 1, 1) + timedelta(days=i)).isoformat() for i in range(365) if (date(2014, 1, 1) + timedelta(days=i)).weekday() < 5}
    counts = {row['market']: len((weekdays | set(row.get('additional_open_dates', {}))) - set(row['dates'])) for row in markets}
    assert counts == {'korea': 245, 'us': 252, 'japan': 244, 'china': 245, 'taiwan': 248, 'europe': 256}, counts
    print(counts)


if __name__ == '__main__':
    main()
