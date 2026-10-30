"""Collect actual 2019 SEC XBRL periods; never infer quarters from annuals."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
import argparse
import hashlib
import json
import math
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError

import stock_information as info
import stock_chart_history as charts
from backfill_yahoo_calendars import _company_name_matches

CACHE = info.ROOT / 'data/tmp_2019/sec'
TAGS = {'revenue':['Revenues','RevenueFromContractWithCustomerExcludingAssessedTax','SalesRevenueNet'],
        'operating_income':['OperatingIncomeLoss'], 'net_income':['NetIncomeLoss']}
PERIODS = ['CY2018','CY2019','CY2018Q4','CY2019Q1','CY2019Q2','CY2019Q3','CY2019Q4','CY2020Q1']


def cached(url):
    CACHE.mkdir(parents=True, exist_ok=True)
    target = CACHE / (hashlib.sha256(url.encode()).hexdigest()+'.json')
    if target.exists(): return json.loads(target.read_bytes())
    time.sleep(.3)
    with urlopen(Request(url, headers={'User-Agent':'Stock Study historical data project research@example.com','Accept':'application/json'}),timeout=45) as response:
        value = json.load(response)
    charts.write_json(target,value)
    charts.write_json(target.with_suffix('.source.json'),{'url':url,'fetched_at':datetime.now(timezone.utc).isoformat(),'sha256':hashlib.sha256(target.read_bytes()).hexdigest()})
    return value


def frame_fact(fact, annual):
    start, end = fact.get('start'), fact.get('end')
    if not start or not end or not '2019-01-01' <= end <= '2019-12-31': return None
    duration = (date.fromisoformat(end)-date.fromisoformat(start)).days+1
    if not (335 <= duration <= 395 if annual else 61 <= duration <= 121): return None
    value = fact.get('val')
    if type(value) not in (int,float) or not math.isfinite(value): return None
    if not isinstance(fact.get('cik'),int) or not fact.get('accn'): return None
    return {'type':'annual' if annual else 'quarterly','period_start':start,'period_end':end,
            'currency':'USD','source':'SEC reported US-GAAP financials','cik':fact['cik'],
            'accession':fact['accn'],'value':value,
            'source_url':f"https://www.sec.gov/Archives/edgar/data/{fact['cik']}/{fact['accn'].replace('-','')}/"}


def collect():
    mapping=cached('https://www.sec.gov/files/company_tickers_exchange.json')
    fields=mapping['fields']
    listings=[dict(zip(fields,row)) for row in mapping['data']]
    roster={row['ticker']:row for row in charts.roster() if row['market']=='us'}
    verified={}
    rejected=[]
    for row in listings:
        ticker=row['ticker'].replace('-','.')
        stock=roster.get(ticker)
        if not stock: continue
        exchange={'Nasdaq':'NASDAQ','NYSE':'NYSE','NYSE American':'AMEX','Cboe':'AMEX'}.get(row['exchange'])
        if exchange != stock['exchange'] or not _company_name_matches(stock['name'], {'longName':row['name']}):
            rejected.append({'ticker':ticker,'roster_name':stock['name'],'sec_name':row['name'],'reason':'Unverified company or exchange'})
            continue
        verified.setdefault(row['cik'],[]).append(ticker)
    tasks=[(metric,tag,priority,period) for metric,tags in TAGS.items() for priority,tag in enumerate(tags) for period in PERIODS]
    def load(task):
        metric,tag,priority,period=task
        url=f'https://data.sec.gov/api/xbrl/frames/us-gaap/{tag}/USD/{period}.json'
        try:
            value=cached(url)
        except HTTPError as error:
            if error.code != 404: raise
            value={'tag':tag,'uom':'USD','taxonomy':'us-gaap','data':[]}
        if value.get('tag')!=tag or value.get('uom')!='USD' or value.get('taxonomy')!='us-gaap': raise ValueError('XBRL identity or currency mismatch')
        return task,value,url
    groups={}
    with ThreadPoolExecutor(max_workers=2) as pool:
        for (metric,tag,priority,period),payload,url in pool.map(load,tasks):
            for fact in payload['data']:
                if fact.get('cik') not in verified:continue
                statement=frame_fact(fact,'Q' not in period)
                if not statement:continue
                for ticker in verified[fact['cik']]:
                    key=(ticker,statement['type'],statement['period_start'],statement['period_end'],statement['accession'])
                    group=groups.setdefault(key,{**{k:v for k,v in statement.items() if k!='value'},'ticker':ticker,'concepts':{},'frame_sources':{},'_priority':{}})
                    if priority < group['_priority'].get(metric,999):
                        group[metric]=statement['value'];group['_priority'][metric]=priority
                        group['concepts'][metric]=tag;group['frame_sources'][metric]=url
            print(f'SEC {tag}/{period}: {len(payload["data"])} original facts',flush=True)
    # Keep each row within one filing, period, unit and reporting entity.
    selected={}
    for group in groups.values():
        key=group['ticker'],group['type'],group['period_end']
        score=(sum(group.get(metric) is not None for metric in TAGS),group['accession'])
        old=selected.get(key)
        if old is None or score > (sum(old.get(metric) is not None for metric in TAGS),old['accession']):selected[key]=group
    statements=[]
    for key,group in sorted(selected.items()):
        group.pop('_priority')
        statements.append(group)
    value={'schema_version':1,'source':'SEC XBRL Frames API','source_url':'https://www.sec.gov/search-filings/edgar-application-programming-interfaces',
           'collected_at':datetime.now(timezone.utc).isoformat(),'basis':'Reported USD values; actual period dates; one filing per row; no inferred quarters',
           'statements':statements}
    charts.write_json(info.ROOT/'data/seed/reported_financials_sec_2019.json',value)
    charts.write_json(info.AUDIT/'2019/sec-collection.json',{'verified_tickers':sum(map(len,verified.values())),'statements':len(statements),'listings':len({s['ticker'] for s in statements}),'rejected':rejected})
    print(f'Saved {len(statements)} original statements for {len({s["ticker"] for s in statements})} listings',flush=True)


def apply():
    import backfill_stock_information_2019 as config
    import backfill_stock_information_2024_h2 as recovery
    config.configure()
    db=info.open_database(recovery.STATE)
    rows=json.loads((info.ROOT/'data/seed/reported_financials_sec_2019.json').read_bytes())['statements']
    grouped={}
    for row in rows:grouped.setdefault(row['ticker'],[]).append({k:v for k,v in row.items() if k!='ticker'})
    now=datetime.now(timezone.utc).isoformat()
    applied=[]
    for ticker,statements in grouped.items():
        raw=db.execute('SELECT value FROM information WHERE ticker=?',(ticker,)).fetchone()
        if not raw:continue
        old=json.loads(raw[0]);updated=recovery.merge(old,statements,now)
        db.execute('UPDATE information SET value=? WHERE ticker=?',(json.dumps(updated,ensure_ascii=False,separators=(',',':')),ticker))
        result={'queried_at':now,'status':'available',**updated[recovery.COVERAGE_KEY],'errors':[],'supplement_source':'SEC XBRL Frames API'}
        db.execute(f'INSERT OR REPLACE INTO {recovery.TABLE} VALUES (?,?)',(ticker,json.dumps(result)))
        applied.append(ticker)
    db.commit();recovery.checkpoint(db,charts.roster());db.close()
    charts.write_json(info.AUDIT/'2019/sec-applied.json',{'tickers':applied,'applied_at':now})
    print(f'Applied SEC statements for {len(applied)} listings',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('mode',choices=['collect','apply']);args=parser.parse_args()
    (collect if args.mode=='collect' else apply)()
