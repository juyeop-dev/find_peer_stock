import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";
import { gunzipSync } from "node:zlib";
const source = await readFile(new URL("../src/dataClient/sectorRankings.ts", import.meta.url), "utf8");
const js = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText;
const { sectorRankings, sortSectors, sortSectorMembers, sectorMoney, sectorLabel, classifiedSectorStock } = await import(`data:text/javascript;base64,${Buffer.from(js).toString("base64")}`);
const stock = (ticker, changes = {}) => ({ ticker, name: ticker, currency: "KRW", date: "2026-10-19", exchange: "KOSPI", sector: "Electronic Technology", industry: "Semiconductors", turnover: 100, market_cap: 1000, returns: { day: 10, week: 5, month: null, quarter: null, year: 30 }, ...changes });
const data = (...stocks) => ({ date: "2026-10-19", stocks });

test("constituent sorting switches direction, preserves zero and keeps missing values last without mutating membership", () => {
  const rows = [stock("B", {name:"나",price:20,returns:{month:0}}),stock("C",{name:"다",price:30,returns:{month:null}}),stock("A",{name:"가",price:10,returns:{month:-3}})];
  assert.deepEqual(sortSectorMembers(rows,"return","desc","month").map(row=>row.ticker),["B","A","C"]);
  assert.deepEqual(sortSectorMembers(rows,"return","asc","month").map(row=>row.ticker),["A","B","C"]);
  assert.deepEqual(sortSectorMembers(rows,"name","asc","month").map(row=>row.ticker),["A","B","C"]);
  assert.deepEqual(sortSectorMembers(rows,"price","desc","month").map(row=>row.ticker),["C","B","A"]);
  assert.deepEqual(rows.map(row=>row.ticker),["B","C","A"]);
});
test("equal-weighted average excludes unavailable returns while preserving zero and native-unit monetary totals", () => {
  const [row] = sectorRankings(data(stock("A"), stock("B", { returns: { day: 0 }, turnover: 0, market_cap: 3000 }), stock("C", { returns: { day: null }, turnover: null, market_cap: null })), "industry", "day", "", "equal");
  assert.equal(row.value, 5); assert.equal(row.returnCount, 2); assert.equal(row.members.length, 3);
  assert.equal(row.turnover, 100); assert.equal(row.turnoverCount, 2); assert.equal(row.marketCap, 4000); assert.equal(row.capCount, 2);
  assert.equal(row.representative.ticker, "B"); assert.equal(row.name, "반도체");
});

test("cap weighting uses estimated beginning caps so a tiny limit-up cannot outweigh large declining refiners", () => {
  const [row] = sectorRankings(data(
    stock("SMALL", { returns: { day: 30 }, market_cap: 130 }),
    stock("LARGE", { returns: { day: -5 }, market_cap: 9500 }),
  ), "industry", "day");
  assert.ok(Math.abs(row.value - (100 * 30 + 10000 * -5) / 10100) < 1e-12);
  assert.equal(row.equalValue, 12.5);
  assert.equal(row.returnCount, 2);
  assert.ok(row.value < 0);
});

test("weighted periods exclude invalid or missing weights, preserve zero and never fall back to equal weighting", () => {
  const cases = [stock("MISSING", { market_cap: null }), stock("ZERO_CAP", { market_cap: 0 }),
    stock("NEGATIVE_CAP", { market_cap: -1 }), stock("INFINITE", { market_cap: Infinity }),
    stock("TOTAL_LOSS", { returns: { day: -100 } }), stock("INVALID_RETURN", { returns: { day: NaN } })];
  const [none] = sectorRankings(data(...cases), "industry", "day");
  assert.equal(none.value, null); assert.equal(none.returnCount, 0);
  const [zero] = sectorRankings(data(...cases, stock("FLAT", { returns: { day: 0 } })), "industry", "day");
  assert.equal(zero.value, 0); assert.equal(zero.returnCount, 1);
  const [week] = sectorRankings(data(stock("A", { returns: { day: 50, week: -10 }, market_cap: 900 }),
    stock("B", { returns: { day: -50, week: 10 }, market_cap: 1100 })), "industry", "week");
  assert.ok(Math.abs(week.value) < 1e-12);
});

test("reviewed refinery membership includes both holding companies and separates power, petrochemicals and petroleum products", () => {
  const originals = ["010950.KS", "096770.KS", "060900.KQ", "078930.KS", "267250.KS", "011170.KS", "011780.KS", "003240.KS", "006730.KQ", "003650.KS"].map(ticker => stock(ticker, { sector: "Energy Minerals", industry: "Oil Refining/Marketing" }));
  const rows = sectorRankings(data(...originals), "industry", "day");
  const refinery = rows.find(row => row.name === "정유·정유 지주");
  assert.deepEqual(refinery.members.map(stock => stock.ticker), ["010950.KS", "096770.KS", "078930.KS", "267250.KS"]);
  assert.equal(rows.find(row => row.name === "석유화학").members.length, 3);
  assert.equal(rows.find(row => row.name === "석유제품·윤활유").members.length, 1);
  assert.equal(rows.find(row => row.name === "대체에너지 발전").members[0].ticker, "060900.KQ");
  assert.equal(rows.find(row => row.name === "호텔·리조트").members[0].ticker, "006730.KQ");
  assert.equal(rows.reduce((sum, row) => sum + row.members.length, 0), originals.length);
  assert.equal(rows.reduce((sum, row) => sum + row.turnover, 0), originals.length * 100);
  assert.ok(refinery.members.every(stock => stock.classificationUrl.startsWith("https://")));
  assert.ok(originals.every(stock => stock.industry === "Oil Refining/Marketing"), "Dated raw snapshots remain intact");
  assert.equal(classifiedSectorStock(originals[2]).sector, "Utilities");
  for (const ticker of ["051910.KS", "006650.KS", "104480.KQ"]) {
    assert.equal(classifiedSectorStock(stock(ticker)).industry, "Petrochemicals");
  }
});

test("2026-10-22 saved source reproduces +1.85% and the corrected refinery view remains negative", async () => {
  const evidence = JSON.parse(await readFile(new URL("../../data/sectors/reviews/2026-10-24.json", import.meta.url), "utf8"));
  const oil = evidence.stocks.filter(stock => stock.industry === evidence.original.industry);
  const oldAverage = oil.reduce((sum, stock) => sum + stock.returns.day, 0) / oil.length;
  assert.equal(oldAverage.toFixed(2), "1.85");
  const row = sectorRankings({date: evidence.date, stocks: evidence.stocks}, "industry", "day").find(row => row.name === "정유·정유 지주");
  assert.equal(row.members.length, 4);
  assert.ok(row.value < -5);
  assert.ok(Math.abs(row.value - evidence.corrected.cap_return) < 1e-12);
  assert.equal(evidence.stocks.find(stock => stock.code === "060900").market_cap, 10769971803);
});

test("dated KRX capitalization enables historical weighting and supersedes the provider-cap estimate", async () => {
  const historical = JSON.parse(gunzipSync(await readFile(new URL("../../data/sectors/daily/2024-07-01.json.gz", import.meta.url))));
  const [refinery] = sectorRankings(historical, "industry", "day").filter(row => row.name === "정유·정유 지주");
  assert.equal(refinery.members.length, 4);
  assert.equal(refinery.returnCount, 4);
  assert.ok(Math.abs(refinery.value - -0.04011752173661187) < 1e-12);
  assert.equal(historical.reconstruction.market_cap_restored, true);
  const october = JSON.parse(gunzipSync(await readFile(new URL("../../data/sectors/daily/2026-10-22.json.gz", import.meta.url))));
  const row = sectorRankings(october, "industry", "day").find(row => row.name === "정유·정유 지주");
  assert.ok(Math.abs(row.value - -5.933468885331321) < 1e-12);
  assert.equal(row.members.find(stock => stock.code === "010950").market_cap, 15739074321600);
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
