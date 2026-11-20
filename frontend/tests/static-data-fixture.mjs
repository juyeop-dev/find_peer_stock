import {mkdtemp, readFile, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join, resolve, sep} from 'node:path';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {createServer} from 'node:http';
import {gzipSync} from 'node:zlib';

export async function staticDataFixture() {
  const directory = await mkdtemp(join(tmpdir(), 'static-data-fixture-'));
  const root = fileURLToPath(new URL('../../', import.meta.url));
  const script = `
import sys,json,gzip,random,hashlib
from pathlib import Path
from datetime import datetime,timedelta,timezone
sys.path.insert(0,str(Path(sys.argv[1])/'scripts'))
from package_static_data import package
root=Path(sys.argv[2]); source=root/'source'; source.mkdir()
def put(name,raw):
 p=source/name; p.parent.mkdir(parents=True,exist_ok=True); p.write_bytes(raw)
def js(name,value,compressed=False):
 raw=json.dumps(value,ensure_ascii=False,separators=(',',':')).encode(); put(name,gzip.compress(raw,mtime=0) if compressed else raw)
prices=[['2013-12-30',70,70],['2014-01-02',71,71]]
for offset in range(400,0,-1):
 day=datetime.now(timezone.utc)-timedelta(days=offset)
 if day.weekday()<5: prices.append([day.date().isoformat(),100+(400-offset)/10,100+(400-offset)/10])
js('stock-history/TEST.json.gz',{'ticker':'TEST','currency':'USD','source':'fixture','fetched_at':'2026-11-16T00:00:00Z','prices':prices},True)
js('credit/index.json',{'generated_at':'2026-11-16T00:00:00Z','latest_date':prices[-1][0],'unit':'KRW million','metric':'margin loan balance','source':'fixture','source_url':'https://example.invalid','history':[{'date':d,'total':v*100000,'kospi':v*60000,'kosdaq':v*40000} for d,v,_ in prices]})
js('chart-catalog.json.gz',[{'ticker':'TEST','name':'fixture','exchange':'NASDAQ','market':'us'}],True)
js('index.json',{'value':123.4567890123,'name':'원본','fetched_at':'2026-11-16T00:00:00Z'})
js('new-highs/korea/2014-01-02.json.gz',{'value':0,'loss':-7},True)
for prefix in ['1a','20']:
 for number in range(10000):
  name='stocks/fixture-'+str(number)+'.json'
  if hashlib.sha256(name.encode()).hexdigest().startswith(prefix): js(name,{'value':number}); break
put('investors/index.json.gz',random.Random(17).randbytes(150000))
publication={'schema_version':1,'revision':'fixture-publication','evidence':{'sha256':'a'*64,'verified_at':'2026-11-16T00:00:00Z'},'kinds':{key:{'selection_start_year':2014,'selection_end_year':2025,'published_items':1,'scope':'observed_with_listing_exceptions'} for key in ['stock_history','credit']}}
a=package(source,root/'a',publication=publication,bundle_bytes=16384,direct_threshold=32000,max_asset_bytes=65536)
js('index.json',{'value':987.654321,'name':'changed','fetched_at':'2026-11-17T00:00:00Z'})
b=package(source,root/'b',publication=publication,bundle_bytes=16384,direct_threshold=32000,max_asset_bytes=65536,previous=Path(a['ready_directory']))
print(json.dumps({'a':a['ready_directory'],'b':b['ready_directory']}))
`;
  const releases = JSON.parse(execFileSync('python', ['-c', script, root, directory], {encoding: 'utf8', windowsHide: true, stdio: ['ignore', 'pipe', 'pipe']}));
  const requests = []; let live = 'a', revoke = false;
  const manifests = Object.fromEntries(await Promise.all(Object.entries(releases).map(async ([key, path]) => [key, JSON.parse(await readFile(join(path, 'manifest.json'), 'utf8'))])));
  const server = createServer(async (request, response) => {
    response.setHeader('Access-Control-Allow-Origin', '*');
    const url = new URL(request.url, 'http://localhost');
    const parts = url.pathname.slice(1).split('/'), mode = parts.shift(), path = parts.join('/');
    response.setHeader('Cache-Control', path==='manifest.json'?'no-cache':'public, max-age=31536000, immutable');
    requests.push({mode, path, range: request.headers.range, origin: request.headers.origin});
    if (request.method === 'OPTIONS') {response.writeHead(204); response.end(); return;}
    try {
      if (!['a','b','live','bad','encoded','denied'].includes(mode) || path.includes('..') || (revoke && mode === 'live' && path !== 'manifest.json')) throw new Error('missing');
      const release = releases[mode === 'live' ? live : mode === 'b' ? 'b' : 'a'];
      let bytes = await readFile(join(release, path));
      if (mode === 'bad' && path.startsWith('blobs/')) bytes = Buffer.from('corrupt');
      if (mode === 'denied') response.removeHeader('Access-Control-Allow-Origin');
      if (mode === 'encoded') {bytes = gzipSync(bytes); response.setHeader('Content-Encoding', 'gzip');}
      response.setHeader('Content-Type', path.endsWith('.json') ? 'application/json' : 'application/octet-stream');
      response.end(bytes);
    } catch {response.writeHead(404); response.end('missing');}
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  return {base: `http://127.0.0.1:${server.address().port}`, directory, requests, manifests,
    setLive(value, revoked = false) {live = value; revoke = revoked;},
    async close() {
      server.closeAllConnections(); await new Promise(resolve => server.close(resolve));
      if (!resolve(directory).startsWith(resolve(tmpdir()) + sep)) throw new Error('Unsafe fixture cleanup');
      await rm(directory, {recursive: true, force: true, maxRetries: 10, retryDelay: 100});
    }};
}
