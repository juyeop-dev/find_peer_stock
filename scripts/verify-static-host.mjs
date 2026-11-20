// Read-only post-upload verification. No tokens or Worker refresh calls.
import {createStaticDataClient, sha256} from '../shared/static-data.mjs';
import {pathToFileURL} from 'node:url';
export async function verifyStaticHost(baseUrl, expectedRevision, paths = ['index.json'], origin = 'https://juyeop-dev.github.io') {
  if (!/^[a-f0-9]{64}$/.test(expectedRevision)) throw new Error('Expected verified revision is required');
  let requests = 0;
  const fetcher = async (url, init) => {
    const response = await fetch(url, {...init, headers: {Origin:origin,
      'User-Agent':'find-peer-stock-static-publisher/1.0 (+https://github.com/juyeop-dev/find_peer_stock)'}}); requests++;
    if (response.ok) {
      const cors = response.headers.get('access-control-allow-origin');
      if (cors !== '*' && cors !== origin) throw new Error('Production static CORS header differs');
      const cache = response.headers.get('cache-control') ?? '';
      if (String(url).endsWith('/manifest.json') ? !cache.includes('no-cache') : !cache.includes('immutable')) throw new Error('Production static cache header differs');
    }
    return response;
  };
  const client = createStaticDataClient({baseUrl,fetcher});
  const manifest = await client.manifest();
  if (manifest.revision !== expectedRevision) throw new Error('Production static revision differs');
  const checked = [];
  for (const path of paths) {
    const bytes = await client.get(path);
    checked.push({path,bytes:bytes.length,sha256:await sha256(bytes)});
  }
  return {checked_at:new Date().toISOString(),revision:manifest.revision,requests,checked,passed:true};
}
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const [base,revision,...paths] = process.argv.slice(2);
  console.log(JSON.stringify(await verifyStaticHost(base,revision,paths.length?paths:undefined)));
}
