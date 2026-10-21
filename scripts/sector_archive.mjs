import { mkdir, readFile, readdir, rename, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { gzipSync, gunzipSync } from "node:zlib";

export function validSectorDate(value) {
  return typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value) && Number.isFinite(Date.parse(value)) && new Date(value).toISOString().slice(0, 10) === value;
}
export async function saveSectorFile(path, value) {
  await mkdir(dirname(path), { recursive: true });
  await writeFile(path + ".tmp", value);
  await rename(path + ".tmp", path);
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
  await mkdir(join(directory, "daily"), { recursive: true });
  const records = [];
  for (const name of (await readdir(join(directory, "daily"))).sort()) {
    if (!/^\d{4}-\d{2}-\d{2}\.json\.gz$/.test(name)) continue;
    const bytes = gunzipSync(await readFile(join(directory, "daily", name)));
    const snapshot = JSON.parse(bytes);
    if (name !== snapshot.date + ".json.gz") throw new Error("Sector archive date mismatch");
    records.push(archiveMetadata(snapshot));
    await saveSectorFile(join(output, "daily", snapshot.date + ".json"), bytes);
  }
  const current = JSON.parse(await readFile(join(directory, "index.json"), "utf8"));
  const latest = archiveMetadata(current);
  const calendar = { schema_version: 1, market: "korea", latest_date: current.date, records: [...records.filter(record => record.date !== current.date), latest].sort((a, b) => a.date.localeCompare(b.date)) };
  const text = JSON.stringify(calendar) + "\n";
  await saveSectorFile(join(directory, "calendar.json"), text);
  await saveSectorFile(join(output, "calendar.json"), text);
  await saveSectorFile(join(output, "index.json"), JSON.stringify(current) + "\n");
  await saveSectorFile(join(output, "daily", current.date + ".json"), JSON.stringify(current) + "\n");
  return calendar;
}
