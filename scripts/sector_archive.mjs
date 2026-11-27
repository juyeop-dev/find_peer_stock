import { mkdir, readFile, readdir, rename, unlink, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { gzipSync, gunzipSync } from "node:zlib";
import { packSectorWeek, sectorWeekStart } from "../shared/sector-week.mjs";

export function validSectorDate(value) {
  return typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value) && Number.isFinite(Date.parse(value)) && new Date(value).toISOString().slice(0, 10) === value;
}
export async function saveSectorFile(path, value) {
  await mkdir(dirname(path), { recursive: true });
  await writeFile(path + ".tmp", value);
  await rename(path + ".tmp", path);
}
export function sectorListingSnapshot(snapshot) {
  return { ...snapshot, stocks: snapshot.stocks.map(({ returns, change_pct, ...stock }) => stock) };
}

export function compactSector(snapshot) {
  const { stocks, ...metadata } = snapshot;
  const stock_fields = [], stock_rows = [], shapes = new Map();
  for (const stock of stocks) {
    const fields = Object.keys(stock);
    const key = JSON.stringify(fields);
    if (!shapes.has(key)) {
      shapes.set(key, stock_fields.length);
      stock_fields.push(fields);
    }
    stock_rows.push([shapes.get(key), ...fields.map(field => stock[field])]);
  }
  return { ...metadata, encoding: "sector-columns-v1", stock_fields, stock_rows };
}
export function archiveMetadata(snapshot) {
  if (snapshot?.schema_version !== 1 || snapshot.market !== "korea" || snapshot.currency !== "KRW" || !validSectorDate(snapshot.date)
    || !Number.isFinite(Date.parse(snapshot.fetched_at)) || !Array.isArray(snapshot.stocks) || !snapshot.stocks.length) throw new Error("Invalid sector snapshot");
  const stocks = snapshot.stocks.filter(stock => stock.date === snapshot.date);
  if (!stocks.length) throw new Error("Sector snapshot has no stocks for its trading date");
  return { date: snapshot.date, fetched_at: snapshot.fetched_at, count: stocks.length, industries: new Set(stocks.map(stock => `${stock.sector}\t${stock.industry}`)).size };
}
export async function archiveSectorSnapshot(directory, snapshot) {
  const metadata = archiveMetadata(snapshot);
  const path = join(directory, "daily", metadata.date + ".json.gz");
  let existing;
  try { existing = JSON.parse(gunzipSync(await readFile(path))); } catch (error) { if (error.code !== "ENOENT") throw error; }
  if (existing && Date.parse(existing.fetched_at) >= Date.parse(metadata.fetched_at)) return false;
  await saveSectorFile(path, gzipSync(JSON.stringify(snapshot) + "\n"));
  return true;
}
export async function publishSectorArchive(directory, output) {
  const current = JSON.parse(await readFile(join(directory, "index.json"), "utf8"));
  archiveMetadata(current);
  const weekly = join(output, "weekly"), archive = join(directory, "daily");
  const dailyName = /^\d{4}-\d{2}-\d{2}\.json\.gz$/;
  const currentName = current.date + ".json.gz";
  const names = new Set([...await readdir(archive), currentName]);
  const records = [], kept = new Set();
  let week = "", snapshots = [];
  async function flush() {
    if (!snapshots.length) return;
    const name = week + ".json.gz";
    await saveSectorFile(join(weekly, name), gzipSync(JSON.stringify(packSectorWeek(snapshots)), { level: 6 }));
    kept.add(name);
  }
  for (const name of [...names].filter(name => dailyName.test(name)).sort()) {
    const snapshot = name === currentName ? current : JSON.parse(gunzipSync(await readFile(join(archive, name))));
    if (name !== snapshot.date + ".json.gz") throw new Error("Sector archive date mismatch");
    records.push(archiveMetadata(snapshot));
    const start = sectorWeekStart(snapshot.date);
    if (start !== week) {
      await flush();
      week = start;
      snapshots = [];
    }
    snapshots.push(sectorListingSnapshot(snapshot));
  }
  await flush();
  const calendar = { schema_version: 1, market: "korea", latest_date: current.date, records };
  const text = JSON.stringify(calendar) + "\n";
  await saveSectorFile(join(directory, "calendar.json"), text);
  await saveSectorFile(join(output, "calendar.json"), text);
  await saveSectorFile(join(output, "index.json"), JSON.stringify(sectorListingSnapshot(current)) + "\n");
  for (const entry of await readdir(weekly, { withFileTypes: true })) {
    if (entry.isFile() && dailyName.test(entry.name) && !kept.has(entry.name)) await unlink(join(weekly, entry.name));
  }
  const legacy = join(output, "daily");
  const previous = await readdir(legacy, { withFileTypes: true }).catch(error => { if (error.code === "ENOENT") return []; throw error; });
  for (const entry of previous) {
    if (entry.isFile() && /^\d{4}-\d{2}-\d{2}\.json(?:\.gz)?$/.test(entry.name)) await unlink(join(legacy, entry.name));
  }
  return calendar;
}
