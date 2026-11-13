"""Check repaired daily reports and complete same-listing Japan price curves."""
from datetime import datetime
import hashlib
import json
import math
import sqlite3
from zoneinfo import ZoneInfo

from archive_paths import monthly_report_path
from stock_chart_history import ROOT, write_json


def main():
    proof=json.loads((ROOT/'data/information-audit/2015/japan-gap-recovery.json').read_bytes())
    curves=json.loads((ROOT/'data/information-audit/2015/japan-price-recovery.json').read_bytes())
    bars={}
    for symbol,record in proof['histories'].items():
        path=ROOT/'data/tmp_tradingview_chart/1D'/(hashlib.sha256(f'{symbol}:1D:3200'.encode()).hexdigest()+'.json')
        value=json.loads(path.read_bytes())
        assert hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()==record['sha256']
        assert value['symbol']==value['info']['pro_name']==symbol and value['info']['source_id']=='TSE'
        assert value['info']['currency_code']=='JPY'
        zone=ZoneInfo(value['info']['timezone'])
        selected={datetime.fromtimestamp(row['timestamp'],zone).date().isoformat():row for row in value['bars']
                  if '2015-12-24'<=datetime.fromtimestamp(row['timestamp'],zone).date().isoformat()<='2015-12-28'}
        assert selected['2015-12-25']['volume']>0
        bars[symbol]=selected
    report=json.loads((ROOT/'data/new-highs/reports/japan/2015-12-25.json').read_bytes())
    for row in report['entries']:
        selected=bars[row['source_symbol']]
        assert row['session_close']==selected['2015-12-25']['close']
        assert row['session_volume']==selected['2015-12-25']['volume']
    report=json.loads(monthly_report_path(ROOT/'data/turnover/reports','japan','2015-12-25').read_bytes())
    ranked=sorted(((selected['2015-12-25']['close']*selected['2015-12-25']['volume'],symbol) for symbol,selected in bars.items()),key=lambda row:(-row[0],row[1]))[:30]
    assert [(row['turnover'],row['source_symbol']) for row in report['entries']]==ranked
    adjacent=json.loads((ROOT/'data/information-audit/2015/japan-adjacent-source.json').read_bytes())
    assert adjacent['date']=='2015-12-28'
    for kind in ['new-highs','turnover']:
        path=ROOT/'data/new-highs/reports/japan/2015-12-28.json' if kind=='new-highs' else monthly_report_path(ROOT/'data/turnover/reports','japan','2015-12-28')
        for row in json.loads(path.read_bytes())['entries']:
            symbol=row['source_symbol']
            record=adjacent['histories'][symbol]
            raw=json.loads((ROOT/'data/tmp_tradingview_chart/1D'/(hashlib.sha256(f'{symbol}:1D:3200'.encode()).hexdigest()+'.json')).read_bytes())
            assert hashlib.sha256(json.dumps(raw,sort_keys=True).encode()).hexdigest()==record['sha256']
            zone=ZoneInfo(raw['info']['timezone'])
            selected=sorted((datetime.fromtimestamp(bar['timestamp'],zone).date().isoformat(),bar['close']) for bar in raw['bars'] if bar['close']>0)
            before=[value for value in selected if value[0]<'2015-12-28']
            today=next(value for value in selected if value[0]=='2015-12-28')
            expected=(today[1]/before[-1][1]-1)*100 if before else None
            assert row['change_pct']==expected,(symbol,row['change_pct'],expected)
    with sqlite3.connect(ROOT/'data/tmp_2015_history/history.sqlite') as db:
        for stock in curves['imported']:
            if stock['alternate']:continue
            value=json.loads(db.execute('SELECT value FROM history WHERE ticker=?',(stock['ticker'],)).fetchone()[0])
            day=next(point for point in value['prices'] if point[0]=='2015-12-25')
            assert day[1]==bars[value['source_symbol']]['2015-12-25']['close']
        for ticker in curves['unverified_excluded']:
            value=json.loads(db.execute('SELECT value FROM history WHERE ticker=?',(ticker,)).fetchone()[0])
            assert not any(point[0]=='2015-12-25' for point in value['prices'])
    result={'date':'2015-12-25','verified_listings':len(bars),'coherent_curves':len(curves['imported']),
            'unverified_excluded':len(curves['unverified_excluded']),'turnover_top30_verified':True,'adjacent_returns_verified':True}
    write_json(ROOT/'data/information-audit/2015/japan-quality.json',result)
    print(json.dumps(result),flush=True)


if __name__=='__main__':main()
