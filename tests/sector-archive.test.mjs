import assert from "node:assert/strict";
import test from "node:test";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { join, resolve, sep } from "node:path";
import { tmpdir } from "node:os";
import { gzipSync, gunzipSync } from "node:zlib";
import { archiveMetadata, archiveSectorSnapshot, publishSectorArchive, saveSectorFile, validSectorDate } from "../scripts/sector_archive.mjs";
import { publishKoreanPriceIndex } from "../scripts/korean_price_index.mjs";
import { expandSectorWeek, packSectorWeek, sectorWeekStart } from "../shared/sector-week.mjs";
const snapshot = (date, fetched_at, price) => ({ schema_version: 1, market: "korea", currency: "KRW", date, fetched_at, stocks: [{ ticker: "005930.KS", date, sector: "Electronic Technology", industry: "Semiconductors", price, change_pct: 1, returns: {day: 1} }] });
const readListing = async (path, date) => {
  const week = JSON.parse(gunzipSync(await readFile(join(path, "weekly", sectorWeekStart(date) + ".json.gz"))));
  return expandSectorWeek(week, date);
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
    const legacy = join(published, "daily", "2026-10-19.json.gz");
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

test("dated stock-price index keeps separate bases and skips an unfinished chart close", async () => {
  const directory = await mkdtemp(join(tmpdir(), "korean-price-index-test-"));
  try {
    const history = join(directory, "stock-history"), sectors = join(directory, "sectors");
    const ticker = "005930.KS";
    const sessions = ["2026-10-19", "2026-10-20", "2026-10-21", "2026-10-22"];
    const chart = {ticker, currency: "KRW", fetched_at: "2026-10-22T04:00:00Z", price_start: sessions[0],
      prices: [[0, 100, 50], [1, 110, 55], [1, 120, 60], [1, 140, 70]], prior_snapshots: [
        {ticker, currency: "KRW", complete_history: true, price_start: "2026-10-16", prices: [[0, 88], [3, 100]]},
      ]};
    await saveSectorFile(join(history, ticker + ".delta-v1.json.gz"), gzipSync(JSON.stringify(chart)));
    for (const [index, date] of sessions.entries()) {
      const observed = snapshot(date, date + "T06:32:00Z", 100 + index * 10);
      observed.source = "TradingView";
      observed.stocks[0].currency = "KRW";
      await archiveSectorSnapshot(sectors, observed);
    }
    assert.equal(await publishKoreanPriceIndex(history, sectors), 5);
    const root = join(history, "korea-daily");
    const index = JSON.parse(await readFile(join(root, "index.json")));
    assert.deepEqual(index.tickers, [[ticker, 0, [1], 2, 0.5]]);
    const last = JSON.parse(gunzipSync(await readFile(join(root, sessions.at(-1) + ".json.gz"))));
    assert.deepEqual(last, {key: index.key, date: sessions.at(-1), rows: [[1, 60], [3, 100], [0, 130]]});
  } finally {
    assert.ok(resolve(directory).startsWith(resolve(tmpdir()) + sep));
    await rm(directory, { recursive: true, force: true });
  }
});
