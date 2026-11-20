// Exact-date investor/index pairs with range-specific caches and calendar proof.
import {readFile, mkdir, writeFile, rename} from 'node:fs/promises';
import {join, dirname} from 'node:path';
import {pathToFileURL} from 'node:url';
import {parseInvestorFlow, investorIndexPage, investorRecord, INVESTOR_MARKETS, investorDate} from '../automation/live-api/src/investors.js';
import {collectionRequest, collectionArgs, sessions} from './collection-request.mjs';

async function save(path, value) {
  await mkdir(dirname(path), {recursive: true});
  await writeFile(path + '.tmp', JSON.stringify(value) + '\n');
  await rename(path + '.tmp', path);
}

export async function collectInvestorHistory(request, {flowPage, indexPage = investorIndexPage, now = new Date(), fetcher = fetch} = {}) {
  // Calendar proof must exist before provider access, including dry-run planning.
  const expected = await sessions(request, 'korea');
  if (!expected.length) throw new Error('No verified Korean sessions in requested range');
  const annual = request.start.endsWith('-01-01') && request.end === request.start.slice(0, 4) + '-12-31';
  const cacheSuffix = annual ? '' : '-' + request.end;
  const loadFlow = flowPage ?? (async (market, page) => {
    const cache = join(request.state, `investors/raw-${market}-${page}${cacheSuffix}.json`);
    let payload;
    try { payload = JSON.parse(await readFile(cache, 'utf8')); }
    catch (error) {
      if (error.code !== 'ENOENT') throw error;
      const response = await fetcher(`https://stock.naver.com/api/domestic/market/trend/daily?${new URLSearchParams({tradeType: 'KRX', marketType: market, startIdx: String(page), pageSize: '200'})}`);
      if (!response.ok) throw new Error(`Source status ${response.status}`);
      payload = await response.json(); await save(cache, payload);
    }
    if (!Array.isArray(payload.content)) throw new Error('Missing investor source content');
    return payload.content.map(row => {
      const date = investorDate(row.bizdate);
      // Unrelated source periods can have different investor classifications.
      return date < request.start || date > request.end ? {date} : parseInvestorFlow(row, market);
    });
  });
  async function pages(market, load, first, label) {
    const result = [], seen = new Set();
    // Historical depth follows the requested dates; this is a source limit,
    // not evidence of coverage or a list of fictional trading sessions.
    const maxPages = Math.max(100, Math.ceil((Date.parse(request.as_of) - Date.parse(request.start)) / 86400000 / 60) + 20);
    for (let page = first; page < first + maxPages; page++) {
      const cache = join(request.state, `investors/${market}-${label}-${page}${cacheSuffix}.json`);
      let rows;
      try { rows = JSON.parse(await readFile(cache, 'utf8')); }
      catch (error) {
        if (error.code !== 'ENOENT') throw error;
        rows = await load(market, page); await save(cache, rows);
      }
      if (!rows.length) throw new Error(`Source ended before requested start: ${market}/${label}`);
      for (const row of rows) {
        investorDate(row.date);
        if (seen.has(row.date)) throw new Error(`Repeated source date: ${market}/${label}/${row.date}`);
        seen.add(row.date);
        if (row.date >= request.start && row.date <= request.end) result.push(row);
      }
      if (rows.at(-1).date < request.start) return result;
    }
    throw new Error(`Incomplete historical source: ${market}/${label}`);
  }
  const batches = await Promise.all(INVESTOR_MARKETS.map(async market => {
    const [flows, indices] = await Promise.all([pages(market, loadFlow, 0, 'flows'), pages(market, indexPage, 1, 'index')]);
    const byDate = new Map(indices.map(row => [row.date, row]));
    const rows = flows.map(flow => {
      const index = byDate.get(flow.date);
      if (!index) throw new Error(`Missing exact index: ${market}/${flow.date}`);
      if (!Array.isArray(flow.investors) || !['personal', 'foreign', 'institution', 'other'].every(key => flow.investors.some(row => row.key === key)) ||
          !flow.investors.every(row => [row.buy, row.sell, row.net].every(Number.isSafeInteger)) || !Number.isFinite(index.close) || index.close <= 0) {
        throw new Error(`Invalid cached investor/index values: ${market}/${flow.date}`);
      }
      return {market, ...flow, index};
    });
    if (JSON.stringify(rows.map(row => row.date).sort()) !== JSON.stringify(expected)) throw new Error(`Incomplete market dates: ${market}`);
    return rows;
  }));
  const source = join(request.root, 'data/investors/index.json');
  const previous = JSON.parse(await readFile(source, 'utf8'));
  const history = new Map(previous.history.map(row => [row.date, row]));
  for (const date of expected) {
    if (!history.has(date)) history.set(date, investorRecord(date, batches.map(rows => rows.find(row => row.date === date)), now));
  }
  const value = {...previous, requested_start: previous.requested_start && previous.requested_start < request.start ? previous.requested_start : request.start,
    generated_at: now.toISOString(), history: [...history.values()].sort((a, b) => a.date.localeCompare(b.date))};
  await save(source, value);
  await save(join(request.root, 'frontend/public/data/investors/index.json'), value);
  await save(join(request.audit, 'investor-progress.json'), {start: request.start, end: request.end, dates: expected.length, markets: INVESTOR_MARKETS, validated_at: now.toISOString()});
  return value;
}

export async function main(argv = process.argv.slice(2), year) {
  const options = collectionArgs(argv, year);
  const request = await collectionRequest(options);
  if (options.dryRun) { console.log(JSON.stringify({...request, verified_sessions: await sessions(request, 'korea')})); return; }
  const value = await collectInvestorHistory(request);
  console.log(`Retained ${value.history.length} exact-date investor/index records`);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) await main();
