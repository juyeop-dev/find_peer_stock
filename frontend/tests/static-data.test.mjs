import assert from 'node:assert/strict';
import {after, test} from 'node:test';
import {gunzipSync} from 'node:zlib';
import {createStaticDataClient, validDataPath, readTar} from '../../shared/static-data.mjs';
import {staticDataFixture} from './static-data-fixture.mjs';
import {verifyStaticHost} from '../../scripts/verify-static-host.mjs';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {join} from 'node:path';
import {fileURLToPath} from 'node:url';
const fixture = await staticDataFixture();
after(() => fixture.close());
const decode = bytes => JSON.parse(new TextDecoder().decode(bytes));

test('exact JSON, raw gzip and legacy JSON alias retain precision, Unicode and source times', async () => {
  const client = createStaticDataClient({baseUrl: fixture.base+'/a'});
  const value = decode(await client.get('index.json'));
  assert.equal(value.value,123.4567890123); assert.equal(value.name,'원본'); assert.equal(value.fetched_at,'2026-11-16T00:00:00Z');
  const raw = await client.get('new-highs/korea/2014-01-02.json.gz');
  assert.equal(raw[0],31); assert.deepEqual(JSON.parse(gunzipSync(raw)), {value:0,loss:-7});
  assert.deepEqual(decode(await client.get('new-highs/korea/2014-01-02.json')), {value:0,loss:-7});
});
test('shared immutable requests deduplicate, stay bounded and do not send Range or cache busters', async () => {
  const before = fixture.requests.length;
  const client = createStaticDataClient({baseUrl: fixture.base+'/a',maxCacheBytes:200000});
  await Promise.all(Array.from({length:8},()=>client.get('index.json')));
  const count = fixture.requests.length;
  await client.get('index.json'); assert.equal(fixture.requests.length,count);
  assert.equal(count-before,3); assert.ok(client.stats().cacheBytes<=200000);
  assert.ok(fixture.requests.every(request=>request.range===undefined));
});
test('segmented data reconstructs and host HTTP gzip decoding is transparent', async () => {
  const a = createStaticDataClient({baseUrl:fixture.base+'/a',maxCacheBytes:32000});
  assert.equal((await a.get('investors/index.json.gz')).length,150000); assert.ok(a.stats().cacheBytes<=32000);
  const encoded = createStaticDataClient({baseUrl:fixture.base+'/encoded'});
  assert.equal(decode(await encoded.get('index.json')).value,123.4567890123);
});
test('corruption, missing paths and cancellation reject without manufacturing current data', async () => {
  const bad = createStaticDataClient({baseUrl:fixture.base+'/bad'});
  await assert.rejects(bad.get('index.json'), /integrity/);
  const good = createStaticDataClient({baseUrl:fixture.base+'/a'});
  await assert.rejects(good.get('missing.json'), /missing/);
  const controller = new AbortController(); controller.abort();
  await assert.rejects(good.get('index.json',{signal:controller.signal}), error=>error.name==='AbortError');
  assert.throws(()=>readTar(new Uint8Array(512),'index.json'),/missing/);
  for (const path of ['../private','a%2fb','/index.json','a\\b','a?x']) assert.equal(validDataPath(path),false);
});
test('manifest revalidation changes versions and one retained version serves old readers', async () => {
  fixture.setLive('a');
  const client = createStaticDataClient({baseUrl:fixture.base+'/live',manifestTtl:0});
  assert.equal(decode(await client.get('index.json')).value,123.4567890123);
  fixture.setLive('b');
  assert.equal(decode(await client.get('index.json')).value,987.654321);
  assert.equal(client.stats().revision,fixture.manifests.b.revision);
  // Retained A descriptors still resolve on the B host.
  const oldReader = createStaticDataClient({baseUrl:fixture.base+'/b',fetcher:(url,init)=>String(url).endsWith('/manifest.json')?Promise.resolve(Response.json(fixture.manifests.a)):fetch(url,init)});
  assert.equal(decode(await oldReader.get('index.json')).value,123.4567890123);
});
test('one subscriber aborts immediately while the shared request completes for another', async () => {
  const client=createStaticDataClient({baseUrl:fixture.base+'/a',fetcher:async (url,init)=>{
    await new Promise(resolve=>setTimeout(resolve,30)); return fetch(url,init);
  }});
  const controller=new AbortController();
  const cancelled=client.get('index.json',{signal:controller.signal});
  const retained=client.get('index.json');
  const rejected=assert.rejects(cancelled,error=>error.name==='AbortError');
  controller.abort(); await rejected;
  assert.equal(decode(await retained).value,123.4567890123); assert.equal(client.stats().pending,0);
});
test('an asset 404 revalidates the root and retries against the newly published version', async () => {
  let roots=0, missing=true;
  const client=createStaticDataClient({baseUrl:fixture.base+'/b',fetcher:async (url,init)=>{
    const path=new URL(url).pathname;
    if(path.endsWith('/manifest.json')) return Response.json(++roots===1?fixture.manifests.a:fixture.manifests.b);
    if(path.includes('/blobs/')&&missing){missing=false;return new Response('',{status:404});}
    return fetch(url,init);
  }});
  assert.equal(decode(await client.get('index.json')).value,987.654321); assert.equal(roots,2);
});
test('altered root metadata never reaches publication consumers', async () => {
  let published=false;
  const client=createStaticDataClient({baseUrl:fixture.base+'/a',fetcher:async()=>Response.json({...fixture.manifests.a,source_files:999}),onPublication:()=>{published=true;}});
  await assert.rejects(client.get('index.json'),/checksum/); assert.equal(published,false);
});
test('post-upload verifier enforces the exact revision, public CORS and immutable headers', async () => {
  const report=await verifyStaticHost(fixture.base+'/a',fixture.manifests.a.revision,['index.json']);
  assert.equal(report.passed,true); assert.equal(report.checked[0].bytes>0,true);
  await assert.rejects(verifyStaticHost(fixture.base+'/a','0'.repeat(64)),/revision differs/);
  await assert.rejects(verifyStaticHost(fixture.base+'/denied',fixture.manifests.a.revision),/CORS/);
});
test('previous-version downloader retains precisely one verified dataset without recursive history', async () => {
  const result=await promisify(execFile)('python',[fileURLToPath(new URL('../../scripts/sync_previous_static.py',import.meta.url)),
    '--base-url',fixture.base+'/b','--output',join(fixture.directory,'downloaded')],{encoding:'utf8',windowsHide:true});
  const report=JSON.parse(result.stdout);
  assert.equal(report.integrity_verified,true); assert.equal(report.revision,fixture.manifests.b.revision);
  assert.equal(report.source_files,fixture.manifests.b.source_files);
});
