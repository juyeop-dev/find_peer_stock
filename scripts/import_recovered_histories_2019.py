"""Keep coherent curves containing confirmed sessions omitted by Yahoo."""
from datetime import date
import hashlib,json
import stock_chart_history as charts
from backfill_european_new_highs import chart_bars
from backfill_yahoo_calendars import archive_ticker


def retain_curve(previous,fresh):
    if previous['ticker']!=fresh['ticker'] or previous['currency']!=fresh['currency']:
        raise ValueError('Recovered listing or currency differs')
    lag=(date.fromisoformat(previous['prices'][-1][0])-date.fromisoformat(fresh['prices'][-1][0])).days
    snapshots=list(previous.get('prior_snapshots',[]))
    primary,alternate=(previous,fresh) if lag>7 else (fresh,previous)
    available={tuple(p) for p in primary['prices']}
    if any(tuple(p) not in available for p in alternate['prices']):
        saved={k:v for k,v in alternate.items() if k!='prior_snapshots'}
        saved.update(complete_history=True,preservation_reason='Complete observed curve retained separately; different adjustments are never spliced')
        fingerprint=lambda curve:(curve['currency'],curve['source'],curve['prices'])
        if not any(fingerprint(s)==fingerprint(saved) for s in snapshots):snapshots.append(saved)
    return {**primary,'prior_snapshots':snapshots},lag>7


def main():
    charts.DATABASE=charts.ROOT/'data/tmp_2019_history/history.sqlite';db=charts.database()
    result={}
    for market,days in [('taiwan',{'2019-09-09'}),('china',{'2019-04-29','2019-04-30'})]:
        universe=json.loads((charts.ROOT/f'data/tmp_2019/{market}-gap-universe.json').read_bytes())
        imported=[];alternates=[]
        for row in universe['rows']:
            path=charts.ROOT/'data/tmp_tradingview_chart/1D'/(hashlib.sha256(f"{row['symbol']}:1D:2800".encode()).hexdigest()+'.json')
            if not path.exists():continue
            raw=path.read_bytes();payload=json.loads(raw)
            try:
                bars=chart_bars(payload,row)
                observed=sorted(days & {str(b.day) for b in bars if b.volume>0})
                if not observed:continue
                value=charts.parse_tradingview(payload,row['symbol'])
            except (ValueError,KeyError,TypeError):continue
            ticker=archive_ticker(row);stored=db.execute('SELECT value FROM history WHERE ticker=?',(ticker,)).fetchone()
            if not stored:continue
            previous=json.loads(stored[0]);value.update(ticker=ticker,requested_bars=2800,source_symbol=row['symbol'],fetched_at=payload['fetched_at'],first_trade_date=previous.get('first_trade_date'))
            value['prices']=[p for p in value['prices'] if p[0]>='2018-12-20']
            if len(value['prices'])<2:continue
            value['historical_2019_extension']={'mode':'complete_original_curve','observed_recovered_dates':observed,'source_sha256':hashlib.sha256(raw).hexdigest(),'cache':path.relative_to(charts.ROOT).as_posix()}
            merged,alternate=retain_curve(previous,value)
            db.execute('UPDATE history SET value=? WHERE ticker=?',(json.dumps(merged,ensure_ascii=False,separators=(',',':'),allow_nan=False),ticker))
            (alternates if alternate else imported).append(ticker)
        db.commit();result[market]={'actual_dates':sorted(days),'coherent_primary_curves':len(imported),'older_alternate_curves':len(alternates),'primary_tickers':imported,'alternate_tickers':alternates}
        print(market,len(imported),'coherent primary curves;',len(alternates),'older alternatives',flush=True)
    charts.export_packs(db);db.close()
    charts.write_json(charts.ROOT/'data/information-audit/2019/recovered-price-curves.json',result)

if __name__=='__main__':main()
