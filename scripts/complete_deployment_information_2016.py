"""Check 2016 coverage of production-only listings without replacing later data."""
from concurrent.futures import ThreadPoolExecutor
import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import json

import stock_chart_history as charts
import stock_information as info
import backfill_stock_information_2016 as year
import backfill_stock_information_2024_h2 as recovery
from refresh_stock_information_history import fallback
from import_recovered_histories_2019 import retain_curve
from extend_stock_history_2023 import join_prices


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--retry-history-errors',action='store_true')
    args=parser.parse_args()
    year.configure()
    rows=charts.roster()
    db=info.open_database(info.ROOT/'data/tmp_2016/deployment-information')
    values={ticker:json.loads(raw) for ticker,raw in db.execute('SELECT ticker,value FROM information')}
    missing=[row for row in rows if 'historical_2016_coverage' not in values.get(row['ticker'],{})]
    proof_path=info.ROOT/'data/information-audit/2016/new-production-listings.json'
    previous_results=json.loads(proof_path.read_bytes()).get('listings',[]) if proof_path.exists() else []
    if args.retry_history_errors:
        retry={r['ticker'] for r in previous_results if not r['history']}
        missing=[row for row in rows if row['ticker'] in retry]
    histories={};results=[]
    def fetch(row):
        statements,errors=recovery.fetch(row)
        try:history=fallback(row)
        except Exception as error:
            recovery.require_source_access(error)
            history=None;errors.append(f'History: {type(error).__name__}: {error}')
        return row,statements,history,errors
    with ThreadPoolExecutor(max_workers=4) as pool:
        for row,statements,history,errors in pool.map(fetch,missing):
            ticker=row['ticker'];now=datetime.now(timezone.utc).isoformat()
            previous=values.get(ticker) or {'ticker':ticker,'requested_start':'2016-01-01','fetched_at':now,'quote':None,'metrics':{},'financials':[],'warnings':['Original current information unavailable']}
            value=recovery.merge(previous,statements,now)
            db.execute('INSERT OR REPLACE INTO information VALUES (?,?)',(ticker,json.dumps(value,ensure_ascii=False)))
            db.commit()
            if history:histories[ticker]=history
            results.append({'ticker':ticker,'periods':value['historical_2016_coverage']['periods'],'history':bool(history),'errors':errors})
            print(f'Production-only listing {ticker}: 2016 periods={len(statements)}, history={bool(history)}',flush=True)
    if missing:
        info.export(db)
        for shard in '0123456789abcdef':
            updates={ticker:value for ticker,value in histories.items() if hashlib.sha256(ticker.encode()).hexdigest()[0]==shard}
            if not updates:continue
            path=charts.PACKS/f'{shard}.json.gz';stored=json.loads(gzip.decompress(path.read_bytes()))
            for ticker,fresh in updates.items():
                old=stored.get(ticker)
                if old and old['currency']==fresh['currency']:
                    joined=join_prices(old,fresh,start='2015-12-20')
                    merged,_=retain_curve(old,joined or fresh)
                elif old:
                    merged={**fresh,'prior_snapshots':[*old.get('prior_snapshots',[]),{k:v for k,v in old.items() if k!='prior_snapshots'}]}
                else:merged=fresh
                stored[ticker]=merged
            raw=json.dumps(stored,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()
            path.write_bytes(gzip.compress(raw,compresslevel=6,mtime=0))
    db.close()
    saved={r['ticker']:r for r in previous_results};saved.update({r['ticker']:r for r in results})
    charts.write_json(proof_path,{'total':len(rows),'checked':len(saved),'listings':list(saved.values()),'checked_at':datetime.now(timezone.utc).isoformat()})
    print(f'Production universe: {len(rows)}, {len(missing)} extra year checks',flush=True)


if __name__=='__main__':main()
