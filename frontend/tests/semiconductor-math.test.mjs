import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const source = await readFile(new URL("../src/dataClient/semiconductorMath.ts", import.meta.url), "utf8");
const javascript = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext,
  target: ts.ScriptTarget.ES2022 } }).outputText;
const { stockReturn, sectorReturn, sectorSeries } = await import(`data:text/javascript;base64,${Buffer.from(javascript).toString("base64")}`);

function stock(ticker, history) {
  return { ticker, history, quote: { status: "stale", price: null, provider_time: null } };
}

test("stock return uses adjusted close across a split", () => {
  const item = stock("A", [
    { date: "2026-10-01", close: 100, adjusted_close: 50, volume: 100 },
    { date: "2026-10-08", close: 60, adjusted_close: 60, volume: 100 },
  ]);
  assert.ok(Math.abs(stockReturn(item, 7) - 20) < 1e-9);
  assert.equal(stockReturn(item, 30), null);
});

test("sector return equally weights available constituents", () => {
  const members = [
    stock("A", [{ date: "2026-10-01", close: 100, adjusted_close: 100 },
      { date: "2026-10-08", close: 120, adjusted_close: 120 }]),
    stock("B", [{ date: "2026-10-01", close: 100, adjusted_close: 100 },
      { date: "2026-10-08", close: 90, adjusted_close: 90 }]),
    stock("C", [{ date: "2026-10-08", close: 50, adjusted_close: 50 }]),
  ];
  const result = sectorReturn(members, 7);
  assert.equal(result.count, 2);
  assert.equal(result.total, 3);
  assert.ok(Math.abs(result.value - 5) < 1e-9);
  assert.ok(Math.abs(sectorSeries(members, 7).at(-1).value - 105) < 1e-9);
});
