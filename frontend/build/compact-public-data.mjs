import {readFile,writeFile,unlink,readdir} from "node:fs/promises";
import {resolve,join,sep} from "node:path";
import {gzipSync,gunzipSync} from "node:zlib";
import assert from "node:assert/strict";

export function compactJsonWhitespace(bytes) {
  const source=bytes.toString("utf8");
  // Match complete quoted strings first. Remove only JSON whitespace outside
  // them; numerical lexemes, escaping and object/array ordering stay exact.
  return Buffer.from(source.replace(/"(?:[^"\\]|\\.)*"|[ \t\r\n]+/g,token=>token.startsWith('"')?token:""));
}

export function compactSector(snapshot) {
  const {stocks,...metadata}=snapshot,stock_fields=[],stock_rows=[];
  for(const stock of stocks) {
    const fields=Object.keys(stock),key=JSON.stringify(fields);
    let shape=stock_fields.findIndex(value=>JSON.stringify(value)===key);
    if(shape<0){shape=stock_fields.length;stock_fields.push(fields);}
    stock_rows.push([shape,...fields.map(field=>stock[field])]);
  }
  return {...metadata,encoding:"sector-columns-v1",stock_fields,stock_rows};
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
