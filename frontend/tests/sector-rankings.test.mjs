import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";
const source = await readFile(new URL("../src/dataClient/sectorRankings.ts", import.meta.url), "utf8");
const js = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText;
const { sectorRankings, sortSectors, sectorMoney, sectorLabel } = await import(`data:text/javascript;base64,${Buffer.from(js).toString("base64")}`);
const stock = (ticker, changes = {}) => ({ ticker, name: ticker, currency: "KRW", date: "2026-10-19", exchange: "KOSPI", sector: "Electronic Technology", industry: "Semiconductors", turnover: 100, market_cap: 1000, returns: { day: 10, week: 5, month: null, quarter: null, year: 30 }, ...changes });
const data = (...stocks) => ({ date: "2026-10-19", stocks });
test("equal-weighted average excludes unavailable returns while preserving zero and native-unit monetary totals", () => {
  const [row] = sectorRankings(data(stock("A"), stock("B", { returns: { day: 0 }, turnover: 0, market_cap: 3000 }), stock("C", { returns: { day: null }, turnover: null, market_cap: null })), "industry", "day");
  assert.equal(row.value, 5); assert.equal(row.returnCount, 2); assert.equal(row.members.length, 3);
  assert.equal(row.turnover, 100); assert.equal(row.turnoverCount, 2); assert.equal(row.marketCap, 4000); assert.equal(row.capCount, 2);
  assert.equal(row.representative.ticker, "B"); assert.equal(row.name, "반도체");
});
test("older sessions and other currencies never affect latest sector gains or totals", () => {
  const rows = sectorRankings(data(stock("A"), stock("OLD", { date: "2026-10-16" }), stock("USD", { currency: "USD" }), stock("KQ", { exchange: "KOSDAQ" })), "sector", "week", "KOSPI");
  assert.equal(rows.length, 1); assert.equal(rows[0].members.length, 1); assert.equal(rows[0].value, 5); assert.equal(rows[0].turnover, 100);
});
test("period switching uses source period returns and entirely missing amounts stay unavailable", () => {
  const [row] = sectorRankings(data(stock("A", { turnover: null, market_cap: null })), "industry", "month");
  assert.equal(row.value, null); assert.equal(row.turnover, null); assert.equal(row.marketCap, null);
  assert.equal(sectorMoney(null), "—"); assert.equal(sectorMoney(0), "0원"); assert.equal(sectorMoney(1.5e12), "1.5조원"); assert.equal(sectorMoney(1.25e9), "12.5억원");
});
test("industry grouping keeps its parent, and rankings put missing values last in both directions", () => {
  const rows = sectorRankings(data(stock("A"), stock("B", { sector: "Finance" }), stock("C", { industry: "Other", turnover: null, returns: { day: null } })), "industry", "day");
  assert.equal(rows.length, 3);
  for (const direction of ["asc", "desc"]) {
    assert.equal(sortSectors(rows, "turnover", direction).at(-1).representative.ticker, "C");
    assert.equal(sortSectors(rows, "return", direction).at(-1).representative.ticker, "C");
  }
  assert.equal(sectorLabel("New source industry"), "New source industry");
});
