// Exercise the browser-compatible reader against the complete real local pack.
import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {readFile, readdir, writeFile, access} from 'node:fs/promises';
import {resolve, join, relative, sep} from 'node:path';
import {createStaticDataClient, sha256} from '../shared/static-data.mjs';

const [releaseInput,originalInput,reportPath] = process.argv.slice(2);
assert.ok(releaseInput && originalInput && reportPath,'release, original data and report paths required');
const release=resolve(releaseInput), original=resolve(originalInput);
const selected=new Set();
async function pick(folder,prefix='',historical=false) {
  let found;
  for(const entry of await readdir(folder,{withFileTypes:true})) {
    const name=prefix+entry.name;
    if(entry.isDirectory()) {const result=await pick(join(folder,entry.name),name+'/',historical); if(result) return result;}
    else if(entry.isFile() && /\.json(?:\.gz)?$/.test(name)) {
      if(!historical || name.includes('2014-01-02')) return name;
      found??=name;
    }
  }
  return historical?undefined:found;
}
for(const kind of ['stock-history','stock-information','calendar-stocks','new-highs','turnover','rebounds','sectors','credit','investors','semiconductor','chart-replay']) {
  const preferred=['new-highs','turnover','rebounds','sectors'].includes(kind)?await pick(join(original,kind),'',true):undefined;
  const name=preferred??await pick(join(original,kind)); if(name) selected.add(kind+'/'+name);
}
selected.add('index.json'); selected.add('chart-catalog.json.gz');
for(const ticker of ['005930.KS','AAPL','7203.T','2330.TW','EURONEXT~3AMC']) {
  for(const kind of ['stock-history','stock-information']) {
    for(const suffix of kind==='stock-history'?['.delta-v1.json.gz','.json.gz','.json']:['.json.gz','.json']) {
      const path=kind+'/'+ticker+suffix;
      if(await access(join(original,path)).then(()=>true,()=>false)) {selected.add(path);break;}
    }
  }
}
const server=createServer(async(request,response)=>{
  try {
    const path=decodeURIComponent(new URL(request.url,'http://localhost').pathname).slice(1);
    assert.ok(path==='manifest.json'||/^(?:blobs|indexes|manifests)\/[a-f0-9]{64}\.(?:tar|bin|json)$/.test(path));
    const target=resolve(release,path); assert.ok(relative(release,target)!=='..'&&!relative(release,target).startsWith('..'+sep));
    response.setHeader('Access-Control-Allow-Origin','*'); response.end(await readFile(target));
  } catch {response.writeHead(404);response.end('missing');}
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
try {
  const client=createStaticDataClient({baseUrl:`http://127.0.0.1:${server.address().port}/`});
  const checked=[];
  for(const path of selected) {
    const bytes=await client.get(path), raw=await readFile(join(original,path));
    assert.deepEqual(Buffer.from(bytes),raw,path);
    checked.push({path,bytes:bytes.length,sha256:await sha256(bytes)});
  }
  const report={checked_at:new Date().toISOString(),revision:(await client.manifest()).revision,checked,passed:true,cache:client.stats()};
  await writeFile(reportPath,JSON.stringify(report,null,2)+'\n');
  console.log(JSON.stringify({passed:true,artifacts:checked.length,total_bytes:checked.reduce((sum,row)=>sum+row.bytes,0),revision:report.revision}));
} finally {server.closeAllConnections();await new Promise(resolve=>server.close(resolve));}
