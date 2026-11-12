"""Restore preserved daily curves and extend them from verified cached daily bars."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
import gzip
import hashlib
import json

import stock_chart_history as charts
import stock_information as info
from extend_stock_history_2023 import cached_yahoo_path, join_prices
from import_recovered_histories_2019 import retain_curve
from refresh_stock_information_history import fallback


def monthly(prices):
    return len(prices)>=12 and sum(point[0][8:]=="01" for point in prices)>=len(prices)*.8


def main():
    charts.DATABASE=charts.ROOT/'data/tmp_2016_history/history.sqlite'
    db=charts.database()
    roster={row['ticker']:row for row in charts.roster()}
    invalid={ticker for ticker,raw in db.execute("SELECT ticker,json_extract(value,'$.prices') FROM history WHERE json_extract(value,'$.requested_range')='max'") if monthly(json.loads(raw))}
    evidence=charts.ROOT/'data/information-audit/2016/daily-frequency-recovery.json'
    if not invalid and evidence.exists():
        assert not json.loads(evidence.read_bytes())['remaining_monthly']
        db.close()
        print('Daily granularity remains valid; original recovery evidence retained',flush=True)
        return
    roster_path=charts.ROOT/'data/information-audit/2016/rejected-monthly-roster.json'
    original_invalid=set(json.loads(roster_path.read_bytes())) if roster_path.exists() else set()
    original_invalid|=invalid
    charts.write_json(roster_path,sorted(original_invalid))
    print(f'Repair {len(invalid)} monthly responses from original daily sources',flush=True)
    repaired=[{'ticker':ticker,'mode':'retained_completed_daily_repair'} for ticker in sorted(original_invalid-invalid)];pending=[]
    for pack in sorted((charts.ROOT/'data/tmp_2016/baseline/stock-history').glob('*.gz')):
        old=json.loads(gzip.decompress(pack.read_bytes()))
        for ticker,baseline in old.items():
            if ticker not in invalid:continue
            current=json.loads(db.execute('SELECT value FROM history WHERE ticker=?',(ticker,)).fetchone()[0])
            value=None
            candidates=[]
            if charts.yahoo_symbol(ticker):candidates.append((cached_yahoo_path(charts.yahoo_symbol(ticker),2016),'yahoo',charts.yahoo_symbol(ticker)))
            row=roster.get(ticker)
            if row:
                for symbol in info.symbols(row):
                    candidates.append((charts.ROOT/'data/tmp_tradingview_chart/1D'/(hashlib.sha256(f'{symbol}:1D:3200'.encode()).hexdigest()+'.json'),'tradingview',symbol))
            for path,provider,symbol in candidates:
                if not path.exists():continue
                try:
                    payload=json.loads(path.read_bytes())
                    older=(charts.parse_yahoo if provider=='yahoo' else charts.parse_tradingview)(payload,symbol)
                    older['ticker']=ticker
                    value=join_prices(baseline,older,start='2015-12-20')
                    if value:
                        value['historical_2016_daily_recovery']={'mode':'verified_daily_prefix','cache':path.relative_to(charts.ROOT).as_posix(),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
                        break
                except (ValueError,KeyError,TypeError):continue
            if not value:
                # A complete cached curve with a revised adjustment basis is
                # valid as one whole original, with previous curves retained.
                for path,provider,symbol in candidates:
                    if provider!='tradingview' or not path.exists():continue
                    try:
                        payload=json.loads(path.read_bytes());fresh=charts.parse_tradingview(payload,symbol)
                        fresh.update(ticker=ticker,prices=[p for p in fresh['prices'] if p[0]>='2015-12-20'],first_trade_date=baseline.get('first_trade_date'))
                        if len(fresh['prices'])<250 or (date.fromisoformat(baseline['prices'][-1][0])-date.fromisoformat(fresh['prices'][-1][0])).days>7:continue
                        value=fresh
                        value['historical_2016_daily_recovery']={'mode':'coherent_cached_daily_original','cache':path.relative_to(charts.ROOT).as_posix(),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
                        break
                    except (ValueError,KeyError,TypeError):continue
            if not value:
                target=charts.ROOT/'data/tmp_2016/daily-restore'/f'{ticker.replace(":","~").replace("/","~")}.json.gz'
                target.parent.mkdir(parents=True,exist_ok=True)
                target.write_bytes(gzip.compress(json.dumps(baseline,ensure_ascii=False,separators=(',',':')).encode(),mtime=0))
                pending.append(ticker)
                continue
            snapshot={k:v for k,v in current.items() if k!='prior_snapshots'}
            snapshot.update(complete_history=False,preservation_reason='Provider returned monthly granularity for a daily max request; retained as provenance only')
            value['prior_snapshots']=[*current.get('prior_snapshots',[]),snapshot]
            db.execute('UPDATE history SET value=? WHERE ticker=?',(json.dumps(value,ensure_ascii=False,separators=(',',':')),ticker))
            repaired.append({'ticker':ticker,'mode':'verified_daily_prefix','first_price':value['prices'][0][0]})
        db.commit()
        print(f'Cached daily prefix repairs: {len(repaired)}; exact daily rechecks: {len(pending)}',flush=True)
    seen={r['ticker'] for r in repaired}|set(pending)
    pending.extend(sorted(invalid-seen))
    def fetch(ticker):
        row=roster[ticker]
        if row['market']=='korea':
            from backfill_korean_new_highs import cached_request,history_url,parse_history
            start,end=date(2015,12,20),datetime.now(timezone.utc).date()
            code=ticker.split('.')[0]
            raw=cached_request(history_url(code,start,end),18,charts.ROOT/'data/tmp_korean_history')
            parsed=parse_history(raw,code=code,start=start,end=end)
            prices=[[str(day),bar[4],bar[4]] for day,bar in sorted(parsed.items()) if bar[4]>0]
            if len(prices)<2:raise ValueError('Original Naver daily history unavailable')
            value={'ticker':ticker,'currency':'KRW','source':'Naver Finance adjusted daily history','source_symbol':'KRX:'+code,
                'fetched_at':datetime.now(timezone.utc).isoformat(),'requested_start':str(start),'requested_range':'dated','prices':prices}
        else:
            value=fallback(row)
        assert not monthly(value['prices'])
        return ticker,value
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures={pool.submit(fetch,ticker):ticker for ticker in pending if ticker in roster}
        for count,future in enumerate(as_completed(futures),1):
            ticker=futures[future]
            try:
                _,fresh=future.result()
                previous=json.loads(db.execute('SELECT value FROM history WHERE ticker=?',(ticker,)).fetchone()[0])
                fresh['prices']=[p for p in fresh['prices'] if p[0]>='2015-12-20']
                fresh['first_trade_date']=fresh.get('first_trade_date') or previous.get('first_trade_date')
                value,_=retain_curve(previous,fresh)
                assert not monthly(value['prices'])
                db.execute('UPDATE history SET value=? WHERE ticker=?',(json.dumps(value,ensure_ascii=False,separators=(',',':')),ticker))
                repaired.append({'ticker':ticker,'mode':'exact_daily_recheck','first_price':value['prices'][0][0]})
            except Exception as error:
                # Restore an intact retained daily original when older history
                # is unavailable; never retain the monthly curve as primary.
                if getattr(error,'code',None) in {403,429}:raise
                current=json.loads(db.execute('SELECT value FROM history WHERE ticker=?',(ticker,)).fetchone()[0])
                alternatives=[p for p in current.get('prior_snapshots',[]) if p.get('complete_history') and len(p.get('prices',[]))>200 and not monthly(p['prices'])]
                baseline_path=charts.ROOT/'data/tmp_2016/daily-restore'/f'{ticker.replace(":","~").replace("/","~")}.json.gz'
                if baseline_path.exists():alternatives.append(json.loads(gzip.decompress(baseline_path.read_bytes())))
                if not alternatives:raise
                best=max(alternatives,key=lambda p:(p['prices'][-1][0],len(p['prices'])))
                snapshot={k:v for k,v in current.items() if k!='prior_snapshots'}
                snapshot.update(complete_history=False,preservation_reason='Rejected monthly response retained outside daily chart')
                value={**best,'prior_snapshots':[*current.get('prior_snapshots',[]),snapshot]}
                db.execute('UPDATE history SET value=? WHERE ticker=?',(json.dumps(value,ensure_ascii=False,separators=(',',':')),ticker))
                repaired.append({'ticker':ticker,'mode':'retained_daily_original','error':str(error),'first_price':value['prices'][0][0]})
            db.commit()
            if count%100==0:print(f'Exact daily rechecks {count}/{len(futures)}',flush=True)
    remaining=[ticker for ticker,raw in db.execute("SELECT ticker,json_extract(value,'$.prices') FROM history WHERE json_extract(value,'$.requested_range')='max'") if monthly(json.loads(raw))]
    assert not remaining,remaining
    charts.write_json(charts.ROOT/'data/information-audit/2016/daily-frequency-recovery.json',{'rejected_monthly':len(original_invalid),'repaired':repaired,'remaining_monthly':remaining,'checked_at':datetime.now(timezone.utc).isoformat()})
    db.close()
    print(f'Repaired {len(repaired)} daily curves; no monthly response remains as a daily primary',flush=True)


if __name__=='__main__':main()
