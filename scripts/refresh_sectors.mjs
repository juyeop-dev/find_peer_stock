import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { join } from "node:path";
import { execFileSync } from "node:child_process";
import { sectors } from "../automation/live-api/src/sectors.js";
import { archiveSectorSnapshot, publishSectorArchive, saveSectorFile } from "./sector_archive.mjs";

const root = fileURLToPath(new URL("../", import.meta.url));
const durable = join(root, "data/sectors/index.json");
const directory = join(root, "data/sectors");
if (process.argv[2] === "restore-history") {
  const commits = execFileSync("git", ["log", "--format=%H", "--", "data/sectors/index.json"], { cwd: root, encoding: "utf8" }).trim().split(/\r?\n/).filter(Boolean);
  let restored = 0;
  for (const [i, sha] of commits.entries()) {
    const snapshot = JSON.parse(execFileSync("git", ["show", `${sha}:data/sectors/index.json`], { cwd: root, encoding: "utf8", maxBuffer: 8 * 1024 * 1024 }));
    if (await archiveSectorSnapshot(directory, snapshot)) restored++;
    if ((i + 1) % 100 === 0) console.log(`Checked ${i + 1}/${commits.length} saved sector snapshots.`);
  }
  console.log(`Restored ${restored} daily snapshots from verified Git history.`);
} else if (process.argv[2] !== "publish") {
  const previous = JSON.parse(await readFile(durable, "utf8"));
  const snapshot = await sectors();
  if (snapshot.date < previous.date) throw new Error("Provider returned an older trading day; retaining the current sector snapshot.");
  // The latest JSON serves intraday requests. Finalize its archive on rollover
  // instead of adding a changing compressed binary to Git every five minutes.
  if (previous.date !== snapshot.date) await archiveSectorSnapshot(directory, previous);
  await saveSectorFile(durable, JSON.stringify(snapshot) + "\n");
  console.log(`Sector snapshot: ${snapshot.stocks.length} stocks, ${snapshot.date}, ${snapshot.stale_count} older bars excluded from ranking.`);
}
const calendar = await publishSectorArchive(directory, join(root, "frontend/public/data/sectors"));
console.log(`Published ${calendar.records.length} sector trading-day records.`);
