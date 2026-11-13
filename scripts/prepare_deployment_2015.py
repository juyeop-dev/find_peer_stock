"""Integrate the reviewed workspace into a separate current-production checkout."""
from pathlib import Path
from datetime import datetime,timezone,timedelta,date
import gzip,json,shutil,hashlib,subprocess
from extend_stock_history_2023 import join_prices
from backfill_semiconductor_history_2015 import fetch as extend_semiconductor

ROOT=Path(__file__).resolve().parents[1]
DEST=ROOT/'data/tmp_2015/deploy-worktree'
BACKUP=DEST/'data/tmp_2015/production-baseline'
REPORT={'checked_at':datetime.now(timezone.utc).isoformat(),'base_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=DEST,text=True).strip()}

def load(path):
    raw=path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.suffix=='.gz' else raw)

def save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    raw=(json.dumps(value,ensure_ascii=False,separators=(',',':'),allow_nan=False)+'\n').encode()
    path.write_bytes(gzip.compress(raw,compresslevel=6,mtime=0) if path.suffix=='.gz' else raw)

def copy(path):
    target=DEST/path.relative_to(ROOT)
    target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(path,target)

for relative in ['data/credit/index.json','data/investors/index.json','data/semiconductor/index.json','data/chart-replay/markets.json']:
 source=DEST/relative; target=BACKUP/Path(relative).relative_to('data'); target.parent.mkdir(parents=True,exist_ok=True)
 if not target.exists():shutil.copy2(source,target)
files = ['.github/workflows/refresh-stock-information.yml', 'scripts/generate_calendar_stock_data.py', 'tests/test_calendar_stock_data.py', 'scripts/backfill_stock_information_2024_h2.py', 'scripts/stock_chart_history.py', 'scripts/calendar_history.py', 'scripts/refresh_investors.mjs', 'scripts/backfill_rebounds.py', 'scripts/stock_information.py', 'scripts/refresh_stock_information_history.py', 'scripts/generate_semiconductor_data.py', 'scripts/backfill_yahoo_calendars.py', 'scripts/audit_calendar_2023.py', 'scripts/refresh_chart_replay.py', 'scripts/archive_paths.py', 'frontend/src/components/StockHistoryChart.tsx', 'frontend/src/dataClient/stockHistoryClient.ts', 'frontend/src/dataClient/stockInformationClient.ts', 'frontend/src/dataClient/investorDataClient.ts', 'frontend/src/dataClient/staticStockDataClient.ts', 'frontend/src/dataClient/sectorDataClient.ts', 'frontend/src/dataClient/chartReplayClient.ts', 'frontend/src/dataClient/reboundClient.ts', 'frontend/src/pages/CreditBalancePage.tsx', 'frontend/src/pages/InvestorFlowsPage.tsx', 'frontend/build/compact-public-data.mjs', 'frontend/vite.config.ts', 'frontend/tests/stock-information.test.mjs', 'frontend/tests/stock-history.test.mjs', 'frontend/tests/investor-flows.test.mjs', 'frontend/tests/historical-report-client.test.mjs', 'frontend/tests/sector-history-client.test.mjs', 'frontend/tests/published-information.mjs', 'frontend/tests/local-api-routing.mjs', 'frontend/tests/rebounds-browser.mjs', 'automation/live-api/src/history.js', 'automation/live-api/src/information.js', 'automation/live-api/src/investors.js', 'automation/live-api/src/providers.js', 'automation/live-api/src/worker.js', 'automation/live-api/test/history.test.mjs', 'automation/live-api/test/information.test.mjs', 'automation/live-api/test/investors.test.mjs', 'tests/test_backfill_yahoo_calendars.py', 'tests/test_new_high_data.py', 'tests/test_generate_semiconductor_data.py', 'tests/test_historical_report_publication.py', 'tests/sector-archive.test.mjs', 'docs/worklogs/stock-information-2015.md', 'data/market-closures/2015.json', 'data/seed/reported_financials_sec_2015.json', 'data/seed/investor_source_exceptions.json']
for name in files: copy(ROOT/name)
# Preserve the deployed quarterly UI and add the reviewed year range.
panel=DEST/'frontend/src/components/StockInformationPanel.tsx'
text=panel.read_text(encoding='utf-8').replace('2016년 1월 1일 이후','2015년 1월 1일 이후').replace('2016년 이후 확정','2015년 이후 확정')
new_line=next(line for line in (ROOT/'frontend/src/components/StockInformationPanel.tsx').read_text(encoding='utf-8').splitlines() if '{data.historical_2015_coverage ?' in line)
if 'data.historical_2015_coverage ?' not in text:text=text.replace('      {data.historical_2016_coverage ?',new_line+'\n      {data.historical_2016_coverage ?')
panel.write_text(text,encoding='utf-8')
for name in ['README.md','automation/live-api/README.md']:
 text=(DEST/name).read_text(encoding='utf-8')
 intro=(ROOT/name).read_text(encoding='utf-8').split('\n\n')[1]
 first=text.index('\n')
 if intro not in text:(DEST/name).write_text(text[:first+1]+'\n'+intro+'\n'+text[first+1:],encoding='utf-8')

for folder in ['scripts','tests','frontend/tests']:
 for path in (ROOT/folder).glob('*2015*'):
  if path.is_file():
   copy(path)
for folder in ['data/information-audit/2015']:
 for path in (ROOT/folder).rglob('*'):
  if path.is_file():copy(path)
for namespace in ['new-highs','turnover']:
 for folder in ['reports','reviews']:
  for path in (ROOT/'data'/namespace/folder).rglob('2015-*.json'):copy(path)
for path in (ROOT/'data/sectors/daily').glob('2015-*.json.gz'):copy(path)
for path in (ROOT/'data/rebounds/reports').rglob('2015-*.json'):copy(path)
copy(ROOT/'data/rebounds/backfill-audit-2015.json')
for name in ['results.csv','results.jsonl','progress.json','history-progress.json','exceptions.json']:
 copy(ROOT/'data/information-audit'/name)
relative = Path('data/new-highs/europe-exchange-closures.json')
prior, incoming = load(DEST/relative), load(ROOT/relative)
prior['closures'] = sorted([r for r in prior['closures'] if not r['date'].startswith('2015-')] + [r for r in incoming['closures'] if r['date'].startswith('2015-')], key=lambda r:(r['date'],r['exchange']))
save(DEST/relative,prior)
relative = Path('data/chart-replay/markets.json')
current, incoming = load(DEST/relative), load(ROOT/relative)
for previous in current['markets']:
 fresh = next(r for r in incoming['markets'] if r['ticker']==previous['ticker'])
 curves = [fresh,*fresh.get('prior_snapshots',[])]
 available = {json.dumps(p,sort_keys=True) for curve in curves for p in curve['bars']}
 if any(json.dumps(p,sort_keys=True) not in available for p in previous['bars']):
  fresh.setdefault('prior_snapshots',[]).append(previous)
save(DEST/relative,incoming)

for kind in ['credit','investors']:
    relative=Path('data')/kind/'index.json'
    old,new=load(ROOT/relative),load(DEST/relative)
    rows={r['date']:r for r in old['history']}
    rows.update({r['date']:r for r in new['history']})
    merged={**new,'history':[rows[key] for key in sorted(rows)]}
    save(DEST/relative,merged)
    assert all(r in merged['history'] for r in new['history'])
    assert all(r in merged['history'] for r in old['history'] if r['date'].startswith('2015-'))
    REPORT[kind]={'preserved_production_days':len(new['history']),'merged_days':len(rows),'2015_days':sum(d.startswith('2015-') for d in rows)}
    if kind=='credit':save(DEST/'frontend/public/data/credit/index.json',merged)

for kind in ['stock-information','stock-history']:
    counts={'merged_listings':0,'production_rows_preserved':0,'incoming_rows_preserved':0,'conflicting_financial_rows_retained':0,'new_production_points_retained':0}
    for path in sorted((ROOT/'data'/kind).glob('*.gz')):
        incoming=load(path)
        target=DEST/'data'/kind/path.name
        backup=BACKUP/kind/path.name;backup.parent.mkdir(parents=True,exist_ok=True)
        if not backup.exists():shutil.copy2(target,backup)
        original=load(backup)
        merged=dict(original)
        for ticker,older in incoming.items():
            current=original.get(ticker)
            if current is None:merged[ticker]=older;continue
            if kind=='stock-information':
                value={**older,**current}
                for key,item in older.items():
                    if key.startswith('historical_2015') or key=='requested_start':value[key]=item
                key=lambda r:(r['type'],r['period_end'],r['currency'])
                rows={key(r):r for r in older.get('financials',[])}
                prior=list(older.get('prior_financial_snapshots',[]))+list(current.get('prior_financial_snapshots',[]))
                for row in current.get('financials',[]):
                    if key(row) in rows and rows[key(row)]!=row:
                        if rows[key(row)] not in prior:prior.append(rows[key(row)])
                        counts['conflicting_financial_rows_retained']+=1
                    rows[key(row)]=row
                value['financials']=sorted(rows.values(),key=lambda r:(r['period_end'],r['type'],r['currency']))
                if prior:value['prior_financial_snapshots']=prior
                dates=[r['period_end'] for r in value['financials']]
                value['financial_coverage']={**value.get('financial_coverage',{}),'first_period':min(dates,default=None),'latest_period':max(dates,default=None)}
                assert all(r in value['financials'] for r in current.get('financials',[])),ticker
                assert all(r in value['financials']+prior for r in older.get('financials',[])),ticker
                counts['production_rows_preserved']+=len(current.get('financials',[]))
                counts['incoming_rows_preserved']+=len(older.get('financials',[]))
            else:
                joined = join_prices(current, older, start='2014-12-20') if len(current['prices']) >= 2 and len(older['prices']) >= 2 and current['currency']==older['currency'] and current['ticker']==older['ticker'] else None
                chosen = joined or (current if current['prices'] and older['prices'] and current['prices'][0][0] <= older['prices'][0][0] and current['prices'][-1][0] >= older['prices'][-1][0] else older)
                value={**chosen,'prices':list(chosen['prices']),'prior_snapshots':list(older.get('prior_snapshots',[]))+list(current.get('prior_snapshots',[]))}
                seen=set(); value['prior_snapshots']=[curve for curve in value['prior_snapshots'] if (key:=hashlib.sha256(json.dumps(curve,sort_keys=True,separators=(',',':')).encode()).hexdigest()) not in seen and not seen.add(key)]
                # Preserve a current complete curve or extend the historical one only with matching adjustments.
                old_by_date={p[0]:p for p in value['prices']}
                overlap=[p for p in current['prices'] if p[0] in old_by_date]
                if current['currency']==value['currency'] and len(overlap)>=3 and all(p==old_by_date[p[0]] for p in overlap):
                    value['prices'] += [p for p in current['prices'] if p[0]>value['prices'][-1][0]]
                    if value['prices'][-1][0]==current['prices'][-1][0]:
                        for field in ['fetched_at','provider_date']:
                            if field in current:value[field]=current[field]
                curves=[value,*value['prior_snapshots']]
                available={currency:{tuple(p) for c in curves if c['currency']==currency for p in c['prices']} for currency in {c['currency'] for c in curves}}
                for curve in [older,*older.get('prior_snapshots',[]),current,*current.get('prior_snapshots',[])]:
                    retained=available.setdefault(curve['currency'],set())
                    missing=[p for p in curve['prices'] if tuple(p) not in retained]
                    if missing:
                        snapshot={k:curve[k] for k in ['ticker','currency','source','fetched_at'] if k in curve}
                        snapshot.update(prices=missing,complete_history=len(missing)==len(curve['prices']),preservation_reason='Original production observations retained during the 2015 deployment')
                        value['prior_snapshots'].append(snapshot);retained.update(map(tuple,missing))
                        counts['new_production_points_retained']+=len(missing)
                # A full native-KRW curve remains available for the latest sector date.
                if current['currency']=='KRW' and current['prices'][-1][0]>value['prices'][-1][0]:
                    last=current['prices'][-1][0];day=date.fromisoformat(last)
                    try:start=day.replace(year=day.year-1).isoformat()
                    except ValueError:start=day.replace(year=day.year-1,day=28).isoformat()
                    anchor=max((p[0] for p in current['prices'] if p[0]<=start),default=current['prices'][0][0])
                    prices=[p for p in current['prices'] if p[0]>=anchor]
                    if prices[0][0]<=start:
                        value['prior_snapshots'].append({k:current[k] for k in ['ticker','currency','source','fetched_at'] if k in current}|{'prices':prices,'complete_history':True,'preservation_reason':'Complete latest-production curve for sector returns; adjustment bases remain separate'})
                available={currency:{tuple(p) for c in [value,*value['prior_snapshots']] if c['currency']==currency for p in c['prices']} for currency in {c['currency'] for c in [value,*value['prior_snapshots']]}}
                for source in [older,current]:
                    for curve in [source,*source.get('prior_snapshots',[])]:
                        assert all(tuple(p) in available[curve['currency']] for p in curve['prices']),ticker
                counts['production_rows_preserved']+=len(current['prices'])
                counts['incoming_rows_preserved']+=len(older['prices'])
            merged[ticker]=value
        save(target,merged);counts['merged_listings']+=len(merged)
        print(kind,path.name,len(merged),flush=True)
    REPORT[kind]=counts

relative=Path('data/semiconductor/index.json')
incoming,current=load(ROOT/relative),load(BACKUP/'semiconductor/index.json')
by_ticker={r['ticker']:r for r in incoming['stocks']}
for row in current['stocks']:
    old=by_ticker.get(row['ticker'])
    if not old:by_ticker[row['ticker']]=row;continue
    compact=lambda points:[[point['date'],point['close'],point['adjusted_close']] for point in points]
    joined=join_prices({'ticker':row['ticker'],'currency':'KRW','prices':compact(row['history'])},
                       {'ticker':old['ticker'],'currency':'KRW','prices':compact(old['history'])},start='2014-12-20',split_only=False)
    history=old['history']
    if joined:
        by_date={point['date']:point for point in old['history']};by_date.update({point['date']:point for point in row['history']})
        history=[{**by_date[day],'close':close,'adjusted_close':adjusted} for day,close,adjusted in joined['prices']]
    marker=old.get('historical_2015_extension')
    cached=ROOT/'data/tmp_2015/semiconductor'/f"{row['ticker']}.json"
    if not joined and cached.exists():
        candidate=extend_semiconductor(row)
        if candidate['history'][-1]['date']>=history[-1]['date'] and candidate['history'][0]['date']<='2015-01-01':
            history=candidate['history'];marker=candidate.get('historical_2015_extension',marker)
    snapshots=list(old.get('prior_history_snapshots',[]))+list(row.get('prior_history_snapshots',[]))
    value={**row,**{key:item for key,item in old.items() if key.startswith('historical_2015')},'history':history,'prior_history_snapshots':snapshots}
    if marker:value['historical_2015_extension']=marker
    curves=[value['history'],*[s['history'] for s in value['prior_history_snapshots']]]
    retained={json.dumps(p,sort_keys=True) for curve in curves for p in curve}
    if any(json.dumps(p,sort_keys=True) not in retained for p in row['history']):
        value['prior_history_snapshots'].append({'history':row['history'],'source_generated_at':current.get('generated_at'),'preservation_reason':'Complete current production curve retained during historical extension'})
    if any(json.dumps(p,sort_keys=True) not in retained for p in old['history']):
        value['prior_history_snapshots'].append({'history':old['history'],'preservation_reason':'Original reviewed historical curve retained during production merge'})
    by_ticker[row['ticker']]=value
save(DEST/relative,{**current,'stocks':list(by_ticker.values())})
save(DEST/'data/information-audit/2015/deployment-integration.json',REPORT)
print(json.dumps(REPORT,indent=2),flush=True)
