import assert from "node:assert/strict";
import test from "node:test";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { join, resolve, sep } from "node:path";
import { tmpdir } from "node:os";
import { gzipSync, gunzipSync } from "node:zlib";
import { archiveMetadata, archiveSectorSnapshot, publishSectorArchive, saveSectorFile, validSectorDate } from "../scripts/sector_archive.mjs";
import { expandSectorWeek, packSectorWeek } from "../shared/sector-week.mjs";
import { expandSectorDay, packSectorDay } from "../shared/sector-day.mjs";
const snapshot = (date, fetched_at, price) => ({ schema_version: 1, market: "korea", currency: "KRW", date, fetched_at, stocks: [{ ticker: "005930.KS", date, sector: "Electronic Technology", industry: "Semiconductors", price, change_pct: 1, returns: {day: 1} }] });
const readListing = async (path, date) => {
  const day = JSON.parse(gunzipSync(await readFile(join(path, "daily", date + ".json.gz"))));
  const lookup = JSON.parse(gunzipSync(await readFile(join(path, "profiles.json.gz"))));
  return expandSectorDay(day, lookup);
};
test("daily archives retain the last real snapshot per trading date and publish distinct historical prices", async () => {
  const directory = await mkdtemp(join(tmpdir(), "sector-archive-test-"));
  try {
    const old = snapshot("2026-10-19", "2026-10-19T06:30:00Z", 100);
    const final = snapshot("2026-10-19", "2026-10-20T00:10:00Z", 120);
    const current = snapshot("2026-10-21", "2026-10-21T06:30:00Z", 140);
    assert.equal(await archiveSectorSnapshot(directory, old), true);
    assert.equal(await archiveSectorSnapshot(directory, final), true);
    assert.equal(await archiveSectorSnapshot(directory, old), false);
    assert.equal(await archiveSectorSnapshot(directory, current), true);
    await saveSectorFile(join(directory, "index.json"), JSON.stringify(current));
    const published = join(directory, "public");
    const legacy = join(published, "weekly", "2026-10-19.json.gz");
    await saveSectorFile(legacy, gzipSync(JSON.stringify(final)));
    const calendar = await publishSectorArchive(directory, published);
    await assert.rejects(readFile(legacy), {code: "ENOENT"});
    assert.deepEqual(calendar.records.map(row => row.date), ["2026-10-19", "2026-10-21"]);
    assert.equal(calendar.latest_date, "2026-10-21");
    assert.equal(calendar.records[0].fetched_at, final.fetched_at);
    const historical = await readListing(published, "2026-10-19");
    assert.deepEqual(historical, {...final, stocks: final.stocks.map(({returns, change_pct, ...stock}) => stock)});
    assert.deepEqual(JSON.parse(gunzipSync(await readFile(join(directory, "daily/2026-10-19.json.gz")))), final);
    const latest = JSON.parse(await readFile(join(published, "index.json"))).stocks[0];
    assert.equal(latest.price, 140);
    assert.equal(latest.returns, undefined);
    assert.deepEqual(JSON.parse(await readFile(join(published, "calendar.json"))), calendar);
    const intraday = snapshot("2026-10-21", "2026-10-21T07:00:00Z", 150);
    await saveSectorFile(join(directory, "index.json"), JSON.stringify(intraday));
    const updated = await publishSectorArchive(directory, published);
    assert.equal(updated.records.at(-1).fetched_at, intraday.fetched_at);
    assert.equal((await readListing(published, "2026-10-21")).stocks[0].price, 150);
    assert.equal((await readListing(published, "2026-10-19")).stocks[0].price, 120);
  } finally {
    assert.ok(resolve(directory).startsWith(resolve(tmpdir()) + sep));
    await rm(directory, { recursive: true, force: true });
  }
});

test("weekly listings preserve row order, listing changes, dated fields, and numeric precision", () => {
  const a = {date: "2026-10-19", stocks: [
    {ticker: "Z", market_cap: 9007199254740991, date: "2026-10-19", market_cap_date: null},
    {ticker: "A", price: 1.123456789, date: "2026-10-16", market_cap_date: "2026-10-19"},
  ]};
  const b = {date: "2026-10-20", stocks: [{ticker: "A", price: 0, sector: "Changed", date: "2026-10-20"}]};
  const v = JSON.parse(JSON.stringify(packSectorWeek([a, b])));
  assert.deepEqual(expandSectorWeek(v, a.date), a);
  assert.deepEqual(expandSectorWeek(v, b.date), b);
  assert.throws(() => expandSectorWeek(v, "2026-10-21"));
});
test("invalid or mismatched dates cannot become archive filenames", () => {
  for (const value of ["2026-02-30", "../index", "2026-1-01", "", null]) assert.equal(validSectorDate(value), false);
  assert.equal(validSectorDate("2024-02-29"), true);
  assert.throws(() => archiveMetadata(snapshot("../../index", "2026-10-21T00:00:00Z", 100)));
  assert.throws(() => archiveMetadata({ ...snapshot("2026-10-21", "invalid", 100) }));
});

test("daily listings keep row order, original price precision, and a matching shared profile lookup", () => {
  const original = { date: "2026-10-19", stocks: [
    { ticker: "Z", market_cap: 9007199254740991, date: "2026-10-19", market_cap_date: null },
    { ticker: "A", price: 1.123456789, turnover: null, date: "2026-10-16", market_cap_date: "2026-10-19" },
  ] };
  const profiles = [], key = "a".repeat(64);
  const packed = { ...packSectorDay(original, profile => profiles.push(profile) - 1), key };
  const lookup = { encoding: "sector-profiles-v1", keys: [key], profiles };
  assert.deepEqual(expandSectorDay(JSON.parse(JSON.stringify(packed)), lookup), original);
  assert.throws(() => expandSectorDay(packed, {...lookup, keys: []}));
});
