import assert from "node:assert/strict";
import test from "node:test";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { join, resolve, sep } from "node:path";
import { tmpdir } from "node:os";
import { archiveMetadata, archiveSectorSnapshot, publishSectorArchive, saveSectorFile, validSectorDate } from "../scripts/sector_archive.mjs";
const snapshot = (date, fetched_at, price) => ({ schema_version: 1, market: "korea", currency: "KRW", date, fetched_at, stocks: [{ ticker: "005930.KS", date, sector: "Electronic Technology", industry: "Semiconductors", price }] });
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
    const calendar = await publishSectorArchive(directory, published);
    assert.deepEqual(calendar.records.map(row => row.date), ["2026-10-19", "2026-10-21"]);
    assert.equal(calendar.latest_date, "2026-10-21");
    assert.equal(calendar.records[0].fetched_at, final.fetched_at);
    assert.equal(JSON.parse(await readFile(join(published, "daily/2026-10-19.json"))).stocks[0].price, 120);
    assert.equal(JSON.parse(await readFile(join(published, "index.json"))).stocks[0].price, 140);
    assert.deepEqual(JSON.parse(await readFile(join(published, "calendar.json"))), calendar);
    const intraday = snapshot("2026-10-21", "2026-10-21T07:00:00Z", 150);
    await saveSectorFile(join(directory, "index.json"), JSON.stringify(intraday));
    const updated = await publishSectorArchive(directory, published);
    assert.equal(updated.records.at(-1).fetched_at, intraday.fetched_at);
    assert.equal(JSON.parse(await readFile(join(published, "daily/2026-10-21.json"))).stocks[0].price, 150);
    assert.equal(JSON.parse(await readFile(join(published, "daily/2026-10-19.json"))).stocks[0].price, 120);
  } finally {
    assert.ok(resolve(directory).startsWith(resolve(tmpdir()) + sep));
    await rm(directory, { recursive: true, force: true });
  }
});
test("invalid or mismatched dates cannot become archive filenames", () => {
  for (const value of ["2026-02-30", "../index", "2026-1-01", "", null]) assert.equal(validSectorDate(value), false);
  assert.equal(validSectorDate("2024-02-29"), true);
  assert.throws(() => archiveMetadata(snapshot("../../index", "2026-10-21T00:00:00Z", 100)));
  assert.throws(() => archiveMetadata({ ...snapshot("2026-10-21", "invalid", 100) }));
});
