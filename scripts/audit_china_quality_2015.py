"""Check repaired daily reports and complete same-listing China price curves."""
from datetime import date, datetime
import hashlib
import json
import math
import sqlite3
from zoneinfo import ZoneInfo

from archive_paths import monthly_report_path
from dated_fx import usd_rates_for_dates
from stock_chart_history import ROOT, write_json


def main():
    proof=json.loads((ROOT/'data/information-audit/2015/china-gap-recovery.json').read_bytes())
    curves=json.loads((ROOT/'data/information-audit/2015/china-price-recovery.json').read_bytes())
    listings={row["symbol"]:row for row in json.loads((ROOT/"data/tmp_2015/china-gap-universe.json").read_bytes())["rows"]}
    bars={}
    for symbol,record in proof['histories'].items():
        path=ROOT/'data/tmp_tradingview_chart/1D'/(hashlib.sha256(f'{symbol}:1D:3200'.encode()).hexdigest()+'.json')
        value=json.loads(path.read_bytes())
        assert hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()==record['sha256']
        assert value['symbol']==value['info']['pro_name']==symbol and value['info']['source_id']==symbol.split(':')[0]
        assert value['info']['currency_code']==listings[symbol]['currency'].upper()
        zone=ZoneInfo(value['info']['timezone'])
        selected={datetime.fromtimestamp(row['timestamp'],zone).date().isoformat():row for row in value['bars']
                  if '2015-02-17'<=datetime.fromtimestamp(row['timestamp'],zone).date().isoformat()<='2015-02-26'}
        assert selected['2015-02-25']['volume']>0
        bars[symbol]=selected
    report=json.loads((ROOT/'data/new-highs/reports/china/2015-02-25.json').read_bytes())
    for row in report['entries']:
        selected=bars[row['source_symbol']]
        assert row['currency']==listings[row['source_symbol']]['currency'].upper()
        assert row['session_close']==selected['2015-02-25']['close']
        assert row['session_volume']==selected['2015-02-25']['volume']
    report=json.loads(monthly_report_path(ROOT/'data/turnover/reports','china','2015-02-25').read_bytes())
    day=date(2015,2,25)
    currencies={listings[symbol]['currency'].upper() for symbol in bars}
    usd={currency:usd_rates_for_dates(currency,{day},ROOT/'data/tmp_calendar_history')[0][day] for currency in currencies|{'CNY'}}
    rates={currency:usd[currency]/usd['CNY'] for currency in currencies}
    assert report['source_metadata']['cny_per_price_currency']==rates
    ranked=sorted(((selected['2015-02-25']['close']*selected['2015-02-25']['volume']*rates[listings[symbol]['currency'].upper()],symbol) for symbol,selected in bars.items()),key=lambda row:(-row[0],row[1]))[:30]
    assert all(row['currency']==listings[row['source_symbol']]['currency'].upper() and row['turnover_currency']=='CNY' for row in report['entries'])
    assert [(row['turnover'],row['source_symbol']) for row in report['entries']]==ranked
    adjacent=json.loads((ROOT/'data/information-audit/2015/china-adjacent-source.json').read_bytes())
    assert adjacent['date']=='2015-02-26'
    for kind in ['new-highs','turnover']:
        path=ROOT/'data/new-highs/reports/china/2015-02-26.json' if kind=='new-highs' else monthly_report_path(ROOT/'data/turnover/reports','china','2015-02-26')
        for row in json.loads(path.read_bytes())['entries']:
            symbol=row['source_symbol']
            assert row['currency']==listings[symbol]['currency'].upper()
            record=adjacent['histories'][symbol]
            raw=json.loads((ROOT/'data/tmp_tradingview_chart/1D'/(hashlib.sha256(f'{symbol}:1D:3200'.encode()).hexdigest()+'.json')).read_bytes())
            assert hashlib.sha256(json.dumps(raw,sort_keys=True).encode()).hexdigest()==record['sha256']
            zone=ZoneInfo(raw['info']['timezone'])
            selected=sorted((datetime.fromtimestamp(bar['timestamp'],zone).date().isoformat(),bar['close']) for bar in raw['bars'] if bar['close']>0)
            before=[value for value in selected if value[0]<'2015-02-26']
            today=next(value for value in selected if value[0]=='2015-02-26')
            expected=(today[1]/before[-1][1]-1)*100 if before else None
            assert row['change_pct']==expected,(symbol,row['change_pct'],expected)
    with sqlite3.connect(ROOT/'data/tmp_2015_history/history.sqlite') as db:
        for stock in curves['imported']:
            if stock['alternate']:continue
            value=json.loads(db.execute('SELECT value FROM history WHERE ticker=?',(stock['ticker'],)).fetchone()[0])
            day=next(point for point in value['prices'] if point[0]=='2015-02-25')
            assert day[1]==bars[value['source_symbol']]['2015-02-25']['close']
        for ticker in curves['unverified_excluded']:
            value=json.loads(db.execute('SELECT value FROM history WHERE ticker=?',(ticker,)).fetchone()[0])
            assert not any(point[0]=='2015-02-25' for point in value['prices'])
    result={'date':'2015-02-25','verified_listings':len(bars),'coherent_curves':len(curves['imported']),
            'unverified_excluded':len(curves['unverified_excluded']),'turnover_top30_verified':True,'adjacent_returns_verified':True}
    write_json(ROOT/'data/information-audit/2015/china-quality.json',result)
    print(json.dumps(result),flush=True)


if __name__=='__main__':main()
