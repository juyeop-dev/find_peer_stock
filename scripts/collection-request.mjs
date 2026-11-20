import {readFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {join, resolve} from 'node:path';
import {resolveHistoryPolicy} from '../shared/history-policy.mjs';
import {verifiedSessions} from '../shared/trading-sessions.mjs';

export const ROOT = fileURLToPath(new URL('../', import.meta.url));
export async function collectionRequest({year, config = join(ROOT, 'config/history-policy.json'), root = ROOT, asOf} = {}) {
  const policy = JSON.parse((await readFile(config, 'utf8')).replace(/^\uFEFF/, ''));
  resolveHistoryPolicy(policy, {asOf});
  if (year !== undefined) policy.collection = {...policy.collection, start_year: year, end_year: year};
  const {collection, as_of} = resolveHistoryPolicy(policy, {asOf});
  const key = year !== undefined ? String(year) : policy.collection.end_year === null ? `${collection.start_year}_onward` :
    collection.start_year === collection.end_year ? String(collection.start_year) : `${collection.start_year}_${collection.end_year}`;
  return {start: collection.start_date, end: collection.end_date, as_of, scope: key,
    state: join(root, `data/tmp_${key}`), audit: join(root, 'data/information-audit', key), root};
}

export function collectionArgs(argv, year) {
  const value = {year};
  for (let index = 0; index < argv.length; index++) {
    const arg = argv[index];
    if (arg === '--dry-run') value.dryRun = true;
    else if (['--history-config', '--year'].includes(arg)) {
      if (!argv[index + 1]) throw new Error(`Missing argument: ${arg}`);
      const next = argv[++index];
      if (arg === '--year' && !/^\d{1,4}$/.test(next)) throw new Error('Invalid year');
      if (arg === '--year') value.year = Number(next); else value.config = resolve(next);
    } else throw new Error(`Unknown argument: ${arg}`);
  }
  return value;
}

export async function sessions(request, market) {
  const calendars = {};
  for (let year = Number(request.start.slice(0, 4)); year <= Number(request.end.slice(0, 4)); year++) {
    calendars[year] = JSON.parse(await readFile(join(request.root, `data/market-closures/${year}.json`), 'utf8'));
  }
  return verifiedSessions(request.start, request.end, market, calendars);
}
