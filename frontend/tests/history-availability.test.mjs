import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {validatePublication, publishedStart, publishedYears, sinceStart, sinceLabel} from '../../shared/history-availability.mjs';
import {resolveHistoryPolicy} from '../../shared/history-policy.mjs';
import {historyAvailabilityUrl} from './compiled-history-availability.mjs';

const publication = JSON.parse(await readFile(new URL('../../shared/published-history.json', import.meta.url), 'utf8'));
const policy = JSON.parse(await readFile(new URL('../../config/history-policy.json', import.meta.url), 'utf8'));
const runtime = await import(historyAvailabilityUrl);

test('publication years derive from audit evidence and stay separate from the collection target', () => {
  const earlier = structuredClone(policy); earlier.collection.start_year = 2013;
  assert.equal(resolveHistoryPolicy(earlier, {asOf: '2026-11-18'}).collection.start_year, 2013);
  assert.equal(publishedStart(publication, 'stock_history'), '2014-01-01');
  assert.deepEqual(runtime.publishedHistoryYears('stock_history'), publishedYears(publication, 'stock_history'));
  assert.ok(!runtime.publishedHistoryYears('stock_history').includes(2013));
});

test('saved since-year and H2 identifiers retain their original dates and labels', () => {
  for (const year of [2013, 2014, 2015, 2025]) {
    assert.equal(sinceStart(`since${year}`), `${year}-01-01`);
    assert.equal(sinceLabel(`since${year}`), `${year}년~`);
  }
  assert.equal(sinceStart('since2024H2'), '2024-07-01');
  assert.equal(sinceLabel('since2024H2'), '2024년 하반기~');
  assert.equal(sinceStart('since0000'), undefined);
  assert.equal(sinceStart('invalid'), undefined);
});

test('unknown kinds and malformed or future publication evidence cannot advertise history', () => {
  assert.equal(publishedStart(publication, 'unpublished'), undefined);
  assert.deepEqual(publishedYears(publication, 'unpublished'), []);
  const bad = structuredClone(publication); bad.evidence.sha256 = 'unchecked';
  assert.throws(() => validatePublication(bad), /Invalid/);
  bad.evidence.sha256 = publication.evidence.sha256; bad.evidence.verified_at = '2099-01-01T00:00:00Z';
  assert.throws(() => validatePublication(bad), /Invalid/);
});
