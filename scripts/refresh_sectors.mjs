import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { sectors } from "../automation/live-api/src/sectors.js";

const root = fileURLToPath(new URL("../", import.meta.url));
const durable = join(root, "data/sectors/index.json");
const published = join(root, "frontend/public/data/sectors/index.json");
async function save(path, text) {
  await mkdir(dirname(path), { recursive: true });
  await writeFile(path + ".tmp", text, "utf8");
  await rename(path + ".tmp", path);
}
if (process.argv[2] !== "publish") {
  const snapshot = await sectors();
  await save(durable, JSON.stringify(snapshot) + "\n");
  console.log(`Sector snapshot: ${snapshot.stocks.length} stocks, ${snapshot.date}, ${snapshot.stale_count} older bars excluded from ranking.`);
}
await save(published, await readFile(durable, "utf8"));
