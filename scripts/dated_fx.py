"""Use exact-date observed FX quotes; never fill a missing day with another day."""
from datetime import timedelta
from datetime import datetime,timezone
import hashlib,json,math
from urllib.request import Request,urlopen
from urllib.error import HTTPError
import xml.etree.ElementTree as ET
from backfill_yahoo_calendars import request_yahoo,parse_bars


def ecb_usd_rates(currency,days,cache_dir):
    url='https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.xml'
    path=cache_dir/'official-fx/ecb-eurofxref-hist.xml'
    if not path.exists():
        with urlopen(Request(url,headers={'User-Agent':'StockStudy historical FX validation'}),timeout=45) as response:raw=response.read()
        ET.fromstring(raw);path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
    raw=path.read_bytes();wanted={str(day):day for day in days};rates={};observations={}
    for cube in ET.fromstring(raw).iter():
        day=cube.attrib.get('time')
        if day not in wanted:continue
        values={child.attrib['currency']:float(child.attrib['rate']) for child in cube if 'currency' in child.attrib}
        values['EUR']=1.0
        if currency not in values or 'USD' not in values:continue
        if not all(math.isfinite(values[key]) and values[key]>0 for key in ['USD',currency]):raise ValueError('Invalid ECB FX observation')
        rates[wanted[day]]=values['USD']/values[currency]
        observations[day]={'USD_per_EUR':values['USD'],f'{currency}_per_EUR':values[currency]}
    return rates,{'provider':'ECB','basis':'Same-date published euro reference rates; direct cross conversion',
                  'url':url,'sha256':hashlib.sha256(raw).hexdigest(),'observations':observations}


def official_usd_rates(currency, days, cache_dir):
    """Same-day Bank of Canada published averages, with their actual unit basis."""
    sources=[]
    def series(code):
        url=f'https://www.bankofcanada.ca/valet/observations/FX{code}CAD/json?start_date={min(days)}&end_date={max(days)}'
        path=cache_dir/'official-fx'/(hashlib.sha256(url.encode()).hexdigest()+'.json')
        if path.exists():raw=path.read_bytes()
        else:
            with urlopen(Request(url,headers={'User-Agent':'StockStudy historical FX validation','Accept':'application/json'}),timeout=30) as response:raw=response.read()
            path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
        value=json.loads(raw);key=f'FX{code}CAD'
        if value.get('seriesDetail',{}).get(key,{}).get('label')!=f'{code}/CAD':raise ValueError('Official FX pair/unit mismatch')
        rows={row['d']:float(row[key]['v']) for row in value.get('observations',[]) if row.get(key,{}).get('v') is not None}
        if any(not math.isfinite(number) or number<=0 for number in rows.values()):raise ValueError('Invalid official FX observation')
        sources.append({'url':url,'sha256':hashlib.sha256(raw).hexdigest(),'series':key,'basis':value['seriesDetail'][key]['description'],'observations':rows})
        return rows
    try:
        usd=series('USD')
        target={str(day):1.0 for day in days} if currency=='CAD' else series(currency)
    except HTTPError as error:
        if error.code!=404:raise
        return ecb_usd_rates(currency,days,cache_dir)
    rates={day:target[str(day)]/usd[str(day)] for day in days if str(day) in target and str(day) in usd}
    provenance={'provider':'Bank of Canada','basis':'Published daily average; used only when same-date Yahoo direct/inverse observations are absent',
                  'source_series':sources,'usd_per_currency_by_date':{str(day):value for day,value in sorted(rates.items())}}
    if missing:=days-rates.keys():
        recovered,source=ecb_usd_rates(currency,missing,cache_dir);rates.update(recovered);provenance['ecb_supplement']=source
    return rates,provenance


def usd_rates_for_dates(currency, sessions, cache_dir):
    days=set(sessions)
    if not days:return {},{}
    if currency=='USD':return {day:1.0 for day in days},{'currency':'USD','basis':'identity conversion'}
    def observed(symbol, quoted_currency, needed, inverse=False):
        payload=request_yahoo(symbol,period1=min(needed),period2=max(needed)+timedelta(days=2),range_name=None,interval='1d',timeout=30,cache_dir=cache_dir)
        result=payload['chart']['result'][0];meta=result['meta']
        if meta.get('symbol')!=symbol or meta.get('currency')!=quoted_currency:
            raise ValueError(f'FX identity/unit mismatch: {symbol}')
        values={bar.day:(1/bar.close if inverse else bar.close) for bar in parse_bars(payload,symbol,meta['exchangeTimezoneName'])
                if bar.day in needed and math.isfinite(bar.close) and bar.close>0}
        return values,{'symbol':symbol,'source_url':f'https://finance.yahoo.com/quote/{symbol}/history/','inverted':inverse,
                       'usd_per_currency_by_date':{str(day):value for day,value in sorted(values.items())}}
    rates,primary=observed(f'{currency}USD=X','USD',days)
    sources=[primary]
    if missing:=days-rates.keys():
        recovered,inverse=observed(f'{currency}=X',currency,missing,True)
        rates.update(recovered);sources.append(inverse)
    if missing:=days-rates.keys():
        recovered,official=official_usd_rates(currency,missing,cache_dir)
        rates.update(recovered);sources.append(official)
    if missing:=days-rates.keys():raise ValueError(f'{currency}: missing exact-date FX: {sorted(map(str,missing))}')
    return rates,{'currency':currency,'sources':sources,'usd_per_currency_by_date':{str(day):value for day,value in sorted(rates.items())}}
