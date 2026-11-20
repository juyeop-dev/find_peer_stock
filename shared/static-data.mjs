import {validatePublication} from './history-availability.mjs';

const HEX = /^[a-f0-9]{64}$/;
const MAX_ASSET = 25 * 1024 * 1024;
const decoder = new TextDecoder('utf-8', {fatal: true});
const encoder = new TextEncoder();
export const sha256 = async bytes => [...new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))].map(value => value.toString(16).padStart(2, '0')).join('');
// JSON.stringify reorders integer-like keys even after object insertion was
// sorted. Serialize keys explicitly: all 256 hex shard prefixes must agree
// with Python sort_keys, including "1a" preceding "20".
const canonical = value => {
  const encode = item => Array.isArray(item) ? '[' + item.map(encode).join(',') + ']'
    : item && typeof item === 'object' ? '{' + Object.keys(item).sort().map(key => JSON.stringify(key) + ':' + encode(item[key])).join(',') + '}'
    : JSON.stringify(item);
  return encode(value) + '\n';
};

export function validDataPath(path) {
  return typeof path === 'string' && path.length > 0 && !/[\\:%?#\x00-\x1f]/.test(path)
    && path.split('/').every(part => part && !part.startsWith('.'));
}
function descriptor(value) {
  if (!value || !HEX.test(value.sha256) || !Number.isSafeInteger(value.size) || value.size < 1 || value.size > MAX_ASSET
      || !validDataPath(value.path) || !new RegExp(`^(blobs|indexes|manifests)/${value.sha256}\\.(tar|bin|json)$`).test(value.path)) {
    throw new Error('Invalid static asset descriptor');
  }
  return value;
}
function fail(message, status) {const error = new Error(message); error.status = status; return error;}
function abort(signal) {if (signal?.aborted) throw signal.reason ?? new DOMException('Aborted', 'AbortError');}
function withSignal(promise, signal) {
  if (!signal) return promise;
  abort(signal);
  return new Promise((resolve, reject) => {
    const cancel = () => reject(signal.reason ?? new DOMException('Aborted', 'AbortError'));
    signal.addEventListener('abort', cancel, {once: true});
    promise.then(resolve, reject).finally(() => signal.removeEventListener('abort', cancel));
  });
}

// Reads only regular USTAR members. No filesystem extraction or Range requests.
export function readTar(bytes, requested) {
  const found = new Set(); let result;
  const field = (offset, size) => decoder.decode(bytes.subarray(offset, offset + size)).split('\0')[0];
  for (let offset = 0; offset + 512 <= bytes.length;) {
    const header = bytes.subarray(offset, offset + 512);
    if (header.every(value => value === 0)) {
      if (!bytes.subarray(offset).every(value => value === 0)) throw new Error('Invalid USTAR trailer');
      if (result === undefined) throw fail('USTAR member missing', 404);
      return result;
    }
    const octal = (position, length) => {
      const text = field(offset + position, length).trim();
      if (!/^[0-7]+$/.test(text)) throw new Error('Invalid USTAR numeric field');
      return Number.parseInt(text, 8);
    };
    let sum = 0;
    for (let index = 0; index < 512; index++) sum += index >= 148 && index < 156 ? 32 : header[index];
    if (sum !== octal(148, 8) || field(offset + 257, 6) !== 'ustar' || ![0, 48].includes(header[156])) throw new Error('Invalid USTAR header');
    const prefix = field(offset + 345, 155), name = `${prefix ? prefix + '/' : ''}${field(offset, 100)}`;
    const size = octal(124, 12), start = offset + 512;
    if (!validDataPath(name) || found.has(name) || !Number.isSafeInteger(size) || start + size > bytes.length) throw new Error('Invalid USTAR member');
    found.add(name);
    if (name === requested) result = bytes.slice(start, start + size);
    offset = start + Math.ceil(size / 512) * 512;
  }
  throw new Error('Truncated USTAR container');
}

export function createStaticDataClient({baseUrl, fetcher = globalThis.fetch.bind(globalThis), manifestTtl = 60000,
  maxCacheBytes = 32 * 1024 * 1024, onPublication = () => {}}) {
  const base = new URL(baseUrl.endsWith('/') ? baseUrl : baseUrl + '/');
  if (base.protocol !== 'https:' && !(base.protocol === 'http:' && ['localhost', '127.0.0.1', '[::1]'].includes(base.hostname))) throw new Error('Static data requires HTTPS');
  if (base.search || base.hash || base.username || base.password) throw new Error('Invalid static data base URL');
  const memory = new Map(), pending = new Map();
  let memoryBytes = 0, current, checkedAt = 0, rootPending;
  function remember(key, value) {
    if (value.length > maxCacheBytes) return;
    while (memoryBytes + value.length > maxCacheBytes && memory.size) {
      const first = memory.keys().next().value; memoryBytes -= memory.get(first).length; memory.delete(first);
    }
    memory.set(key, value); memoryBytes += value.length;
  }
  async function fetchBytes(path, cache, expected) {
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 30000);
    try {
      const response = await fetcher(new URL(path, base), {cache, credentials: 'omit', mode: 'cors', signal: controller.signal});
      if (!response.ok) throw fail(`Static asset unavailable (${response.status})`, response.status);
      const chunks = []; let total = 0;
      const reader = response.body?.getReader();
      if (!reader) throw new Error('Empty static response');
      for (;;) {
        const {done, value} = await reader.read(); if (done) break;
        total += value.length;
        if (total > MAX_ASSET || (expected && total > expected.size)) {await reader.cancel(); throw new Error('Static asset integrity check failed');}
        chunks.push(value);
      }
      const bytes = new Uint8Array(total); let offset = 0;
      for (const chunk of chunks) {bytes.set(chunk, offset); offset += chunk.length;}
      if (expected && (bytes.length !== expected.size || await sha256(bytes) !== expected.sha256)) throw new Error('Static asset integrity check failed');
      return bytes;
    } finally {clearTimeout(timer);}
  }
  async function asset(value) {
    descriptor(value);
    const cached = memory.get(value.path);
    if (cached) {memory.delete(value.path); memory.set(value.path, cached); return cached;}
    if (!pending.has(value.path)) pending.set(value.path, fetchBytes(value.path, 'force-cache', value).then(bytes => {
      remember(value.path, bytes); return bytes;
    }).finally(() => pending.delete(value.path)));
    return pending.get(value.path);
  }
  async function manifest(force = false) {
    if (!force && current && Date.now() - checkedAt < manifestTtl) return current;
    if (!rootPending) rootPending = (async () => {
      const value = JSON.parse(decoder.decode(await fetchBytes('manifest.json', 'no-cache')));
      if (value.schema_version !== 1 || value.format !== 'static-dataset-v1' || !HEX.test(value.revision) || !HEX.test(value.source_inventory_sha256)
          || !Number.isSafeInteger(value.source_files) || value.source_files < 1 || !value.shards || Array.isArray(value.shards)) throw new Error('Invalid static data manifest');
      for (const [prefix, shard] of Object.entries(value.shards)) {
        if (!/^[a-f0-9]{2}$/.test(prefix)) throw new Error('Invalid static data shard');
        descriptor(shard);
      }
      const {revision, previous, ...core} = value;
      if (await sha256(encoder.encode(canonical(core))) !== revision) throw new Error('Static manifest checksum differs');
      validatePublication(value.publication);
      onPublication(value.publication);
      current = value; checkedAt = Date.now(); return value;
    })().finally(() => {rootPending = undefined;});
    return rootPending;
  }
  async function lookup(value, path) {
    const shard = value.shards[(await sha256(encoder.encode(path))).slice(0, 2)];
    if (!shard) return undefined;
    const index = JSON.parse(decoder.decode(await asset(shard)));
    if (index.schema_version !== 1 || !index.entries || Array.isArray(index.entries)) throw new Error('Invalid static data index');
    return Object.hasOwn(index.entries, path) ? index.entries[path] : undefined;
  }
  async function read(value, path) {
    let entry = await lookup(value, path), compressedAlias = false;
    if (!entry && path.endsWith('.json')) {entry = await lookup(value, path + '.gz'); compressedAlias = Boolean(entry);}
    if (!entry) throw fail(`Static data path missing: ${path}`, 404);
    if (!HEX.test(entry.sha256) || !Number.isSafeInteger(entry.size) || entry.size < 1 || entry.size > 512 * 1024 * 1024) throw new Error('Invalid static data entry');
    let bytes;
    if (entry.format === 'ustar-v1') {
      if (entry.entry !== path + (compressedAlias ? '.gz' : '')) throw new Error('USTAR entry path mismatch');
      bytes = readTar(await asset(entry.container), entry.entry);
    } else if (['raw-v1', 'segments-v1'].includes(entry.format)) {
      if (!Array.isArray(entry.parts) || !entry.parts.length || (entry.format === 'raw-v1' && entry.parts.length !== 1)
          || entry.parts.reduce((sum, part) => sum + descriptor(part).size, 0) !== entry.size) throw new Error('Invalid static data segments');
      // Fetch sequentially to bound memory and concurrent bandwidth for large files.
      bytes = new Uint8Array(entry.size); let offset = 0;
      for (const part of entry.parts) {const raw = await asset(part); bytes.set(raw, offset); offset += raw.length;}
    } else throw new Error('Unsupported static data encoding');
    if (bytes.length !== entry.size || await sha256(bytes) !== entry.sha256) throw new Error('Static entry integrity check failed');
    if (compressedAlias && bytes[0] === 31 && bytes[1] === 139) bytes = new Uint8Array(await new Response(new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'))).arrayBuffer());
    return bytes;
  }
  return {
    manifest,
    async get(path, {signal} = {}) {
      abort(signal);
      return withSignal((async () => {
      if (!validDataPath(path)) throw new Error('Invalid logical static data path');
      abort(signal); let value = await manifest();
      try {const bytes = await read(value, path); abort(signal); return bytes;}
      catch (error) {
        abort(signal);
        if (error.status !== 404) throw error;
        const next = await manifest(true);
        if (next.revision === value.revision) throw error;
        const bytes = await read(next, path); abort(signal); return bytes;
      }
      })(), signal);
    },
    clear() {memory.clear(); memoryBytes = 0; current = undefined; checkedAt = 0;},
    stats() {return {cacheBytes: memoryBytes, cachedAssets: memory.size, pending: pending.size, revision: current?.revision};},
  };
}
