"""Identify preserved whole curves using the exact pre-migration original."""
from pathlib import Path
from datetime import date
import gzip
import json
import stock_chart_history as charts

def main():
    baseline=charts.ROOT/'data/tmp_2020/baseline/stock-history'
    marked=0
    recent=0
    snapshot=json.loads((charts.ROOT/'data/sectors/index.json').read_bytes())
    sector_dates={row['ticker']:row['date'] for row in snapshot['stocks'] if row['date']==snapshot['date']}
    for path in charts.PACKS.glob('*.json.gz'):
        previous=json.loads(gzip.decompress((baseline/path.name).read_bytes()))
        current=json.loads(gzip.decompress(path.read_bytes()))
        changed=False
        for ticker,value in current.items():
            old=previous.get(ticker)
            if not old:continue
            for snapshot in value.get('prior_snapshots',[]):
                if not snapshot.get('complete_history') and snapshot.get('currency')==old.get('currency') and snapshot.get('prices')==old.get('prices'):
                    snapshot['complete_history']=True;marked+=1;changed=True
            end=sector_dates.get(ticker)
            if end and old.get('currency')==value.get('currency') and not any(point[0]==end for point in value['prices']):
                day=date.fromisoformat(end)
                start=day.replace(year=day.year-1,day=28 if (day.month,day.day)==(2,29) else day.day).isoformat()
                originals=[point for point in old['prices'] if point[0]<=end]
                baselines=[i for i,point in enumerate(originals) if point[0]<=start]
                prior=value.setdefault('prior_snapshots',[])
                if originals and originals[-1][0]==end and baselines and not any(curve.get('complete_history') and curve['currency']==value['currency'] and curve['prices'][0][0]<=start and any(point[0]==end for point in curve['prices']) for curve in prior):
                    prior.append({**{k:old[k] for k in ['ticker','currency','source','fetched_at'] if k in old},
                        'prices':originals[baselines[-1]:], 'complete_history':True,
                        'preservation_reason':'Complete original one-year segment for the current sector date; no mixed adjustment bases'})
                    recent+=1;changed=True
        if changed:
            temporary=path.with_suffix('.gz.tmp')
            temporary.write_bytes(gzip.compress(json.dumps(current,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode(),compresslevel=9,mtime=0))
            temporary.replace(path)
    charts.write_json(charts.ROOT/'data/information-audit/2020/complete-prior-histories.json',{'complete_original_curves_marked':marked,'complete_original_year_segments':recent,'basis':'Exact equality with pre-migration original prices and currency'})
    print(f'Marked {marked} original curves and retained {recent} complete original year segments',flush=True)

if __name__=='__main__':main()
