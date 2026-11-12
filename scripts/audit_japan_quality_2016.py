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
    proof=json.loads((ROOT/'data/information-audit/2016/japan-gap-recovery.json').read_bytes())
    curves=json.loads((ROOT/'data/information-audit/2016/japan-price-recovery.json').read_bytes())
    bars={}
    for symbol,record in proof['histories'].items():
        path=ROOT/'data/tmp_tradingview_chart/1D'/(hashlib.sha256(f'{symbol}:1D:3200'.encode()).hexdigest()+'.json')
        value=json.loads(path.read_bytes())
        assert hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()==record['sha256']
        assert value['symbol']==value['info']['pro_name']==symbol and value['info']['source_id']=='TSE'
        assert value['info']['currency_code']=='JPY'
        zone=ZoneInfo(value['info']['timezone'])
        selected={datetime.fromtimestamp(row['timestamp'],zone).date().isoformat():row for row in value['bars']
                  if '2016-07-08'<=datetime.fromtimestamp(row['timestamp'],zone).date().isoformat()<='2016-07-12'}
        assert selected['2016-07-11']['volume']>0
        bars[symbol]=selected
    report=json.loads((ROOT/'data/new-highs/reports/japan/2016-07-11.json').read_bytes())
    for row in report['entries']:
        selected=bars[row['source_symbol']]
        assert row['session_close']==selected['2016-07-11']['close']
        assert row['session_volume']==selected['2016-07-11']['volume']
    report=json.loads(monthly_report_path(ROOT/'data/turnover/reports','japan','2016-07-11').read_bytes())
    ranked=sorted(((selected['2016-07-11']['close']*selected['2016-07-11']['volume'],symbol) for symbol,selected in bars.items()),key=lambda row:(-row[0],row[1]))[:30]
    assert [(row['turnover'],row['source_symbol']) for row in report['entries']]==ranked
    for kind in ['new-highs','turnover']:
        path=ROOT/'data/new-highs/reports/japan/2016-07-12.json' if kind=='new-highs' else monthly_report_path(ROOT/'data/turnover/reports','japan','2016-07-12')
        for row in json.loads(path.read_bytes())['entries']:
            symbol=row.get('source_symbol') or 'TSE:'+row['ticker'].split('.')[0]
            selected=bars.get(symbol,{})
            a,b=selected.get('2016-07-11'),selected.get('2016-07-12')
            expected=(b['close']/a['close']-1)*100 if a and b else None
            assert row['change_pct']==expected
    with sqlite3.connect(ROOT/'data/tmp_2016_history/history.sqlite') as db:
        for stock in curves['imported']:
            if stock['alternate']:continue
            value=json.loads(db.execute('SELECT value FROM history WHERE ticker=?',(stock['ticker'],)).fetchone()[0])
            day=next(point for point in value['prices'] if point[0]=='2016-07-11')
            assert day[1]==bars[value['source_symbol']]['2016-07-11']['close']
        for ticker in curves['unverified_excluded']:
            value=json.loads(db.execute('SELECT value FROM history WHERE ticker=?',(ticker,)).fetchone()[0])
            assert not any(point[0]=='2016-07-11' for point in value['prices'])
    result={'date':'2016-07-11','verified_listings':len(bars),'coherent_curves':len(curves['imported']),
            'unverified_excluded':len(curves['unverified_excluded']),'turnover_top30_verified':True,'adjacent_returns_verified':True}
    write_json(ROOT/'data/information-audit/2016/japan-quality.json',result)
    print(json.dumps(result),flush=True)


if __name__=='__main__':main()
