import assert from 'node:assert/strict';
import test from 'node:test';
import {compactPriceArchive,compactPublicData} from '../build/compact-public-data.mjs';
import {mkdtemp,mkdir,writeFile,readFile,access,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {gzipSync,gunzipSync} from 'node:zlib';
import {expandPriceArchive} from './compiled-price-archive.mjs';

test('price archives preserve actual dates, precision, metadata and independent prior curves',()=>{
  const original={ticker:'TEST',currency:'USD',source:'Original',prices:[['2014-12-26',12.1234567890123,12.1234567890123],['2014-12-27',13,6.5],['2014-12-29',14,7],['2016-02-29',15,15]],prior_snapshots:[{currency:'JPY',prices:[['2012-02-29',100,50],['2012-03-02',101,50.5]]},{prices:[],complete_history:false}]};
  const encoded=compactPriceArchive(original);
  assert.deepEqual(encoded.prices.map(row=>row[0]),[0,1,2,427]);
  assert.equal(encoded.prices[0].length,2);
  assert.equal(encoded.prices[1].length,3);
  assert.deepEqual(expandPriceArchive(JSON.parse(JSON.stringify(encoded))),original);
  assert.equal(original.prices[0][0],'2014-12-26');
});
test('legacy archives remain unchanged',()=>{
  for(const original of [null,[],{ticker:'OLD',prices:[['2014-01-02',1,1]]}])assert.equal(expandPriceArchive(original),original);
});
test('invalid dates, gaps, prices and encodings fail explicitly',()=>{
  const valid={encoding:'stock-history-delta-v1',price_start:'2014-01-02',prices:[[0,1],[1,2]]};
  for(const change of [{encoding:'future-v2'},{price_start:'2014-02-30'},{price_start:'0000-01-01'},{prices:[[1,1]]},{prices:[[0,1],[0,2]]},{prices:[[0,1],[-1,2]]},{prices:[[0,1],[1.5,2]]},{prices:[[0,1],[Number.MAX_SAFE_INTEGER,2]]},{prices:[[0,0]]},{prices:[[0,1,NaN]]},{prices:[]},{prior_snapshots:{}}])assert.throws(()=>expandPriceArchive({...valid,...change}));
  assert.deepEqual(expandPriceArchive({...valid,price_start:null,prices:[]}),{prices:[]});
  assert.throws(()=>compactPriceArchive({prices:[['2014-01-02',1,1],['2014-01-02',2,2]]}));
});

test('artifact archives use a versioned URL and remain lossless on repeated packaging',async()=>{
  const folder=await mkdtemp(join(tmpdir(),'price-archive-test-'));
  try {
    const directory=join(folder,'data/stock-history');await mkdir(directory,{recursive:true});
    const original={ticker:'EXAMPLE',currency:'USD',source:'original',prices:Array.from({length:1000},(_,index)=>[new Date(Date.UTC(2014,0,2+index)).toISOString().slice(0,10),100+index/10,100+index/10])};
    const legacy=join(directory,'EXAMPLE.json.gz'),packed=join(directory,'EXAMPLE.delta-v1.json.gz');
    await writeFile(legacy,gzipSync(JSON.stringify(original)));
    await compactPublicData(folder);
    await assert.rejects(access(legacy),{code:'ENOENT'});
    const bytes=await readFile(packed);
    assert.deepEqual(expandPriceArchive(JSON.parse(gunzipSync(bytes))),original);
    await compactPublicData(folder);assert.deepEqual(await readFile(packed),bytes);
  } finally {await rm(folder,{recursive:true,force:true});}
});
