import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {gzipSync} from 'node:zlib';
import ts from 'typescript';

const source=await readFile(new URL('../src/dataClient/staticStockDataClient.ts',import.meta.url),'utf8');
const js=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText
  .replace(/^import .*;\r?\n/gm,'').replaceAll('import.meta.env.BASE_URL','"/"');
const code='const liveReportFor=()=>null,liveQuoteFor=()=>undefined;\n'+js;
const client=await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`);
const sample={market:'taiwan',date:'2021-04-06',entries:[{ticker:'2330.TW',name:'原本',price:123.4567890123,change_pct:0,profit:-7}]};

test('historical reports decode gzip and already decoded host responses without changing precision or Unicode',async()=>{
  const oldFetch=globalThis.fetch,oldWindow=globalThis.window;globalThis.window=globalThis;
  try {
    for(const encoded of [true,false]) {
      const requests=[];
      globalThis.fetch=async url=>{requests.push(url);return new Response(encoded?gzipSync(JSON.stringify(sample)):JSON.stringify(sample));};
      assert.deepEqual(await client.getNewHighReport('taiwan','2021-04-06'),sample);
      assert.equal(requests.length,1);assert.match(requests[0],/2021-04-06\.json\.gz\?/);
    }
  } finally {globalThis.fetch=oldFetch;globalThis.window=oldWindow;}
});

test('legacy JSON remains readable after a gzip miss and recent completed Korean turnover stays JSON',async()=>{
  const oldFetch=globalThis.fetch,oldWindow=globalThis.window;globalThis.window=globalThis;
  try {
    const calls=[];
    globalThis.fetch=async url=>{calls.push(url);return url.includes('.json.gz?')?new Response('',{status:404}):Response.json(sample);};
    assert.deepEqual(await client.getNewHighReport('taiwan','2021-04-06'),sample);
    assert.equal(calls.length,2);assert.match(calls[1],/2021-04-06\.json\?/);
    calls.length=0;await client.getTurnoverReport('korea','2026-10-29');
    assert.equal(calls.length,1);assert.match(calls[0],/korea\/2026_10\/2026-10-29\.json\?/);
  } finally {globalThis.fetch=oldFetch;globalThis.window=oldWindow;}
});

test('corrupt compressed observations fail instead of silently producing an empty daily report',async()=>{
  const oldFetch=globalThis.fetch,oldWindow=globalThis.window;globalThis.window=globalThis;
  try {globalThis.fetch=async()=>new Response(new Uint8Array([0x1f,0x8b,0,0]));await assert.rejects(()=>client.getNewHighReport('taiwan','2021-04-06'));}
  finally {globalThis.fetch=oldFetch;globalThis.window=oldWindow;}
});
