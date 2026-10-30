import {gunzipSync} from 'node:zlib';
export async function fetchPublishedInformation(base,ticker) {
  const path=base+`/data/stock-information/${encodeURIComponent(ticker).replaceAll('%','~')}.json`;
  let response=await fetch(path+'.gz');
  if(response.status===404)response=await fetch(path);
  if(!response.ok)throw new Error(`Published information HTTP ${response.status}: ${ticker}`);
  const bytes=Buffer.from(await response.arrayBuffer());
  return JSON.parse((bytes[0]===0x1f&&bytes[1]===0x8b?gunzipSync(bytes):bytes).toString('utf8'));
}
