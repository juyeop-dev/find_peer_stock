import {readFile,writeFile,unlink,readdir} from "node:fs/promises";
import {resolve,join,sep} from "node:path";
import {gzipSync,gunzipSync} from "node:zlib";
import assert from "node:assert/strict";
import {compactSector} from "../../scripts/sector_archive.mjs";
export {compactSector};

export function compactJsonWhitespace(bytes) {
  const source=bytes.toString("utf8");
  // Match complete quoted strings first. Remove only JSON whitespace outside
  // them; numerical lexemes, escaping and object/array ordering stay exact.
  return Buffer.from(source.replace(/"(?:[^"\\]|\\.)*"|[ \t\r\n]+/g,token=>token.startsWith('"')?token:""));
}

export function compactPriceArchive(value) {
  assert.equal(value.encoding,undefined);
  const curve=source=>{
    assert.ok(!Object.hasOwn(source,'price_start'));
    assert.ok(Array.isArray(source.prices));
    let previous;
    const prices=source.prices.map((row,index)=>{
      assert.ok(Array.isArray(row)&&row.length===3&&typeof row[0]==='string'&&/^\d{4}-\d{2}-\d{2}$/.test(row[0]));
      const day=Date.parse(row[0]+'T00:00:00Z')/86400000;
      assert.ok(Number.isSafeInteger(day)&&row[0]>='0001-01-01'&&row[0]<='9999-12-31'&&new Date(day*86400000).toISOString().slice(0,10)===row[0]);
      assert.ok(row.slice(1).every(number=>typeof number==='number'&&Number.isFinite(number)&&number>0));
      const delta=index===0?0:day-previous;assert.ok(index===0||delta>0);previous=day;
      return row[1]===row[2]?[delta,row[1]]:[delta,row[1],row[2]];
    });
    return {...source,price_start:source.prices[0]?.[0]??null,prices,
      ...(source.prior_snapshots===undefined?{}:{prior_snapshots:source.prior_snapshots.map(curve)})};
  };
  return {...curve(value),encoding:'stock-history-delta-v1'};
}

export async function compactPublicData(output) {
  const data=join(resolve(output),"data");
  let saved=0,files=0;
  const compress=async path=>{
    const bytes=await readFile(path),compressed=gzipSync(bytes,{level:9});
    assert.deepEqual(gunzipSync(compressed),bytes);
    await writeFile(path+".gz",compressed);
    await unlink(path);
    saved+=bytes.length-compressed.length;files++;
  };
  // Source/public files stay readable JSON; only the finished artifact changes.
  for(const relative of ["semiconductor/index.json","investors/index.json","chart-replay/markets.json","sectors/index.json"]) {
    try {await compress(join(data,relative));}catch(error){if(error.code!=="ENOENT")throw error;}
  }
  const compactReports=async directory=>{
    const entries=await readdir(directory,{withFileTypes:true}).catch(error=>{if(error.code==="ENOENT")return [];throw error;});
    for(const entry of entries) {
      const path=join(directory,entry.name);
      if(entry.isDirectory()){await compactReports(path);continue;}
      if(!entry.name.endsWith('.json')&&!entry.name.endsWith('.json.gz'))continue;
      const encoded=await readFile(path),compressed=entry.name.endsWith('.gz');
      const bytes=compressed?gunzipSync(encoded):encoded;
      if(bytes[0]!==0x7b||![0x0a,0x0d].includes(bytes[1]))continue;
      const compact=compactJsonWhitespace(bytes);
      assert.deepEqual(JSON.parse(compact),JSON.parse(bytes));
      const output=compressed?gzipSync(compact,{level:9}):compact;
      if(output.length<encoded.length){await writeFile(path,output);saved+=encoded.length-output.length;files++;}
    }
  };
  for(const kind of ['new-highs','turnover'])await compactReports(join(data,kind));
  const historyRoot=join(data,'stock-history');
  for(const name of await readdir(historyRoot).catch(error=>{if(error.code==='ENOENT')return [];throw error;})) {
    if(!name.endsWith('.json.gz')||name.endsWith('.delta-v1.json.gz'))continue;
    const path=join(historyRoot,name),bytes=await readFile(path),original=JSON.parse(gunzipSync(bytes));
    if(original.encoding==='stock-history-delta-v1')continue;
    const compact=compactPriceArchive(original);
    const compressed=gzipSync(JSON.stringify(compact)+'\n',{level:9});
    // A distinct URL keeps cached older clients from parsing numeric day gaps
    // as legacy ISO dates. They retain their existing original-provider fallback.
    if(compressed.length<bytes.length){await writeFile(join(historyRoot,name.replace(/\.json\.gz$/,'.delta-v1.json.gz')),compressed);await unlink(path);saved+=bytes.length-compressed.length;files++;}
  }
  const reboundRoot=join(data,"rebounds/korea");
  for(const folder of await readdir(reboundRoot,{withFileTypes:true}).catch(error=>{if(error.code==="ENOENT")return [];throw error;})) {
    if(!folder.isDirectory()||!/^\d{4}_\d{2}$/.test(folder.name))continue;
    for(const name of await readdir(join(reboundRoot,folder.name))) {
      if(/^\d{4}-\d{2}-\d{2}\.json$/.test(name)&&name.slice(0,10)<"2026-11-01")await compress(join(reboundRoot,folder.name,name));
    }
  }
  const sectorRoot=join(data,"sectors/daily");
  for(const name of await readdir(sectorRoot).catch(error=>{if(error.code==="ENOENT")return [];throw error;})) {
    if(!/^\d{4}-\d{2}-\d{2}\.json\.gz$/.test(name))continue;
    const path=join(sectorRoot,name),bytes=await readFile(path),snapshot=JSON.parse(gunzipSync(bytes));
    if(snapshot.encoding||!Array.isArray(snapshot.stocks))continue;
    const compact=compactSector(snapshot);
    const restored={...snapshot,stocks:compact.stock_rows.map(([shape,...values])=>Object.fromEntries(compact.stock_fields[shape].map((key,index)=>[key,values[index]])))};
    assert.deepEqual(restored,snapshot);
    const compressed=gzipSync(JSON.stringify(compact)+"\n",{level:9});
    if(compressed.length<bytes.length){await writeFile(path,compressed);saved+=bytes.length-compressed.length;files++;}
  }
  console.log(`Lossless public data compaction: ${files} files, ${(saved/1024**2).toFixed(2)} MiB saved.`);
  return {files,saved};
}

export function compactPublicDataPlugin() {
  let output;
  return {name:"compact-public-data",apply:"build",configResolved(config){
    output=resolve(config.root,config.build.outDir);
    const source=resolve(config.publicDir);
    if(output===source||source.startsWith(output+sep))throw new Error("Build output must be separate from source public data");
  },async closeBundle(){await compactPublicData(output);}};
}
