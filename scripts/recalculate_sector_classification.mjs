// Reuse the exact public classification and return math when rebuilding history.
import { readFile, readdir } from "node:fs/promises";
import { createRequire } from "node:module";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { gzipSync, gunzipSync } from "node:zlib";
import { saveSectorFile } from "./sector_archive.mjs";

const root = fileURLToPath(new URL("../", import.meta.url));
const require = createRequire(new URL("../frontend/package.json", import.meta.url));
const ts = require("typescript");
const source = await readFile(join(root, "frontend/src/dataClient/sectorRankings.ts"), "utf8");
const js = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText;
const { classifiedSectorStock, sectorRankings, sectorLabel } = await import(`data:text/javascript;base64,${Buffer.from(js).toString("base64")}`);
const directory = join(root, "data/sectors");
const auditPath = join(root, "data/korea-history-recalculation/2026-10-25.json");
const audit = JSON.parse(await readFile(auditPath, "utf8"));
let rankingRecords = [];

for (const name of (await readdir(join(directory, "daily"))).sort()) {
  if (!/^\d{4}-\d{2}-\d{2}\.json\.gz$/.test(name)) continue;
  const path = join(directory, "daily", name);
  const snapshot = JSON.parse(gunzipSync(await readFile(path)));
  const corrected = { ...snapshot, stocks: snapshot.stocks.map(stock => {
    const classified = classifiedSectorStock(stock);
    return { ...classified, source_sector: stock.source_sector ?? stock.sector,
      source_industry: stock.source_industry ?? stock.industry };
  }), classification_review_date: "2026-10-24" };
  const periodRows = Object.fromEntries(["day", "week", "month", "quarter", "year"].map(period => [period,
    sectorRankings(corrected, "industry", period).map(row => ({key: row.key, name: row.name,
      cap_return: row.value, equal_return: row.equalValue, calculated: row.returnCount, count: row.members.length}))]));
  rankingRecords.push({date: corrected.date, periods: periodRows});
  await saveSectorFile(path, gzipSync(JSON.stringify(corrected) + "\n", {mtime: 0}));
}
// The latest provider snapshot is intentionally not rewritten: the regular
// collector owns it. The public UI applies the same classification on read.
const current = JSON.parse(await readFile(join(directory,"index.json"),"utf8"));
rankingRecords.push({date: current.date, latest_provider_snapshot: true,
  periods: Object.fromEntries(["day", "week", "month", "quarter", "year"].map(period => [period,
    sectorRankings(current,"industry",period).map(row => ({key:row.key,name:row.name,cap_return:row.value,
      equal_return:row.equalValue,calculated:row.returnCount,count:row.members.length}))]))});

let reports = 0;
const turnover = join(root,"data/turnover/reports/korea");
for (const month of await readdir(turnover)) {
  if (!/^\d{4}_\d{2}$/.test(month)) continue;
  for (const file of await readdir(join(turnover,month))) {
    if (!/^\d{4}-\d{2}-\d{2}\.json$/.test(file)) continue;
    const path=join(turnover,month,file);
    const report=JSON.parse(await readFile(path,"utf8"));
    report.entries=report.entries.map(entry=>{
      const classified=classifiedSectorStock(entry);
      return {...entry,sector:sectorLabel(classified.sector),industry:sectorLabel(classified.industry)};
    });
    await saveSectorFile(path,JSON.stringify(report,null,2)+"\n");
    reports++;
  }
}
audit.classified_turnover_dates=reports;
rankingRecords=[...new Map(rankingRecords.map(record=>[record.date,record])).values()];
audit.sector_dates=rankingRecords.length;
audit.sector_periods=["day","week","month","quarter","year"];
audit.classification_review_date="2026-10-24";
audit.rankings_file="rankings-2026-10-25.json.gz";
audit.refinery_examples=rankingRecords.filter(record=>["2024-07-01","2026-10-22"].includes(record.date))
  .map(record=>({date:record.date,...record.periods.day.find(row=>row.key.endsWith("Refining & Holdings"))}));
await saveSectorFile(join(root,"data/korea-history-recalculation",audit.rankings_file),gzipSync(JSON.stringify(rankingRecords)+"\n"));
await saveSectorFile(auditPath,JSON.stringify(audit,null,2)+"\n");
console.log(`Recalculated all five periods for ${audit.sector_dates} sector dates; classified ${reports} Korean turnover dates.`);
