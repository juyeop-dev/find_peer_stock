import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

let source = await readFile(new URL("../src/dataClient/stockHistoryClient.ts", import.meta.url), "utf8");
source = source.replace('import { liveDetailFor, requestOriginal } from "./liveStockDataClient";', 'const liveDetailFor = () => undefined; const requestOriginal = () => { throw new Error("unit test should not request live data"); };');
const javascript = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText;
const { chartStart, historyRange, yearCovered, getStockHistory } = await import(`data:text/javascript;base64,${Buffer.from(javascript).toString("base64")}`);
const point = date => ({ date, close: 100, adjusted_close: 100, volume: null });

test("one year follows calendar dates including leap days instead of using 360 days", () => {
  assert.equal(chartStart("2026-10-20", "since2024H2"), "2024-07-01");
  assert.equal(chartStart("2026-10-20", "since2025"), "2025-01-01");
  assert.equal(chartStart("2026-10-19", "1y"), "2025-10-19");
  assert.equal(chartStart("2024-02-29", "1y"), "2023-02-28");
  assert.equal(chartStart("2025-02-28", "1y"), "2024-02-28");
  assert.equal(chartStart("2026-10-19", "2y"), "2024-10-19");
});
test("a non-trading anniversary includes its previous close, and a recent IPO keeps its actual data", () => {
  const full = ["2025-10-01", "2025-10-17", "2025-10-20", "2026-10-19"].map(point);
  assert.equal(historyRange(full, "1y")[0].date, "2025-10-17");
  assert.ok(yearCovered(full));
  const recent = ["2026-06-01", "2026-10-19"].map(point);
  assert.deepEqual(historyRange(recent, "1y"), recent);
  assert.equal(yearCovered(recent), false);
  assert.deepEqual(historyRange([], "1y"), []);
});

test("a fresh short inline snapshot cannot hide the published H2-2024 archive", async () => {
  const originalFetch = globalThis.fetch;
  const today = new Date().toISOString().slice(0, 10);
  // Resolve Vite's base path before transpiling this network path.
  const patched = javascript.replaceAll("import.meta.env.BASE_URL", '"/"');
  const client = await import(`data:text/javascript;base64,${Buffer.from(patched).toString("base64")}`);
  globalThis.fetch = async () => Response.json({ticker:"TEST",currency:"USD",source:"verified",fetched_at:new Date().toISOString(),prices:[["2024-06-28",10,10],[today,20,20]]});
  try {
    const result = await client.getStockHistory("TEST", undefined, undefined, false, {ticker:"TEST",currency:"USD",source:"short inline",fetched_at:new Date().toISOString(),history:[point("2025-01-01"),point(today)]});
    assert.equal(result.history[0].date,"2024-06-28");
    assert.equal(result.source,"verified");
  } finally { globalThis.fetch = originalFetch; }
});
