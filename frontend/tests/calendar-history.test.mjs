import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const source = await readFile(new URL("../src/dataClient/calendarHistory.ts", import.meta.url), "utf8");
const javascript = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext,
  target: ts.ScriptTarget.ES2022 } }).outputText;
const { historyDays, summarizeDays, mergeHistoryStocks, formatHistoryMoney } = await import(`data:text/javascript;base64,${Buffer.from(javascript).toString("base64")}`);

test("daily aggregation preserves recorded zero and excludes missing dates and other markets", () => {
  const highs = { reports: [
    { market: "korea", date: "2026-01-05", counts: { total: 0, high_52_week: 0, high_all_time: 0 } },
    { market: "us", date: "2026-01-02", counts: { total: 99, high_52_week: 99, high_all_time: 0 } },
    { market: "korea", date: "2026-01-02", counts: { total: 3, high_52_week: 2, high_all_time: 1 } },
  ] };
  const days = historyDays(highs, { reports: [] }, "new-highs", "korea");
  assert.deepEqual(days.map(day => day.date), ["2026-01-02", "2026-01-05"]);
  assert.deepEqual(summarizeDays(days), { days: 2, count: 3, high52: 2, highAll: 1, money: {} });
});

test("yearly unique tickers merge months without mutating archive or counting twice", () => {
  const stock = (dates, high52, highAll, money) => ({ ticker: "A", name: "회사", exchange: "EX", category: "산업",
    dates, high_52_week: high52, high_all_time: highAll, turnover_by_currency: money });
  const archive = { months: [
    { month: "2026-02", stocks: [{ ...stock(["2026-02-02"], 0, 1, { USD: 300, GBP: 20 }), name: "새 이름" }] },
    { month: "2026-01", stocks: [stock(["2026-01-02"], 1, 0, { USD: 100 })] },
  ] };
  const snapshot = structuredClone(archive);
  const yearly = mergeHistoryStocks(archive, "2026");
  assert.equal(yearly.length, 1);
  assert.deepEqual(yearly[0].dates, ["2026-01-02", "2026-02-02"]);
  assert.equal(yearly[0].name, "새 이름");
  assert.equal(yearly[0].high_52_week + yearly[0].high_all_time, 2);
  assert.deepEqual(yearly[0].turnover_by_currency, { USD: 400, GBP: 20 });
  assert.equal(mergeHistoryStocks(archive, "2026-01")[0].dates.length, 1);
  assert.deepEqual(mergeHistoryStocks(archive, "2025"), []);
  assert.deepEqual(archive, snapshot);
});

test("monetary totals preserve currencies and support older calendar indexes", () => {
  const turnover = { reports: [
    { market: "europe", date: "2026-01-02", count: 2, total_turnover: 150, currency: "USD", turnover_by_currency: { USD: 100, GBP: 50 } },
    { market: "europe", date: "2026-01-05", count: 1, total_turnover: 10, currency: "USD" },
  ] };
  assert.deepEqual(summarizeDays(historyDays({ reports: [] }, turnover, "turnover", "europe")).money, { USD: 110, GBP: 50 });
  assert.equal(formatHistoryMoney({ USD: 1e12, GBP: 1e8 }), "1억 GBP · 1조 USD");
  assert.equal(formatHistoryMoney({}), "—");
});
