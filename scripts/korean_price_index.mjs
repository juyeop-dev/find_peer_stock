import { createHash } from "node:crypto";
import { mkdir, readFile, readdir, unlink, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { gzipSync, gunzipSync } from "node:zlib";
import { saveSectorFile } from "./sector_archive.mjs";

const stockFile = /^([0-9A-Z]{6}\.(?:KS|KQ))(\.delta-v1)?\.json\.gz$/;
const stockTicker = /^[0-9A-Z]{6}\.(?:KS|KQ)$/;
const dailyFile = /^\d{4}-\d{2}-\d{2}\.json\.gz$/;
const DAY = 86400000;
const HOUR = 3600000;
const dayNumber = date => Date.parse(date) / DAY;
const isoDay = number => new Date(number * DAY).toISOString().slice(0, 10);
const positive = value => Number.isFinite(value) && value > 0;
const exchangeClose = day => day * DAY + 6.5 * HOUR;

function readCurve(value) {
  let day = value.price_start == null ? null : dayNumber(value.price_start);
  let previous = -Infinity;
  const points = value.prices.map(([date, close, adjusted = close], index) => {
    if (typeof date === "number" && (!Number.isInteger(date) || day === null || (index === 0 ? date !== 0 : date <= 0))) {
      throw new Error(`Invalid daily price gap for ${value.ticker}`);
    }
    day = typeof date === "number" ? day + date : dayNumber(date);
    if (!Number.isInteger(day) || day <= previous || !positive(close) || !positive(adjusted)) {
      throw new Error(`Invalid daily price curve for ${value.ticker}`);
    }
    previous = day;
    return [day, close, adjusted];
  });
  const last = points.at(-1);
  const fetched = Date.parse(value.fetched_at);
  // The last chart bar may have been collected during the session. A closed
  // observation is required in the historical view and for linking sources.
  if (last && fetched >= last[0] * DAY - 9 * HOUR && fetched < exchangeClose(last[0])) points.pop();
  return points;
}

// Link the two sources only when their price scales agree across several
// shared sessions. An isolated recent quote curve also works on its own.
function quoteScale(prices, quotes) {
  const references = [];
  const observed = new Map(quotes.map(([day, price]) => [day, price]));
  for (let i = prices.length - 1; i >= 0 && references.length < 3; i--) {
    const [day, , adjusted] = prices[i];
    if (observed.has(day)) references.push(adjusted / observed.get(day));
  }
  const latest = references[0];
  return references.length === 3 && references.every(value => Math.abs(value / latest - 1) <= 0.001) ? latest : null;
}

async function readObservedQuotes(sectorDirectory) {
  const quotes = new Map();
  const daily = join(sectorDirectory, "daily");
  const files = (await readdir(daily)).filter(name => dailyFile.test(name)).sort();
  for (const name of files) {
    const snapshot = JSON.parse(gunzipSync(await readFile(join(daily, name))));
    if (snapshot.reconstruction || snapshot.source !== "TradingView" || Date.parse(snapshot.fetched_at) < exchangeClose(dayNumber(snapshot.date))) continue;
    const stocks = snapshot.stocks ?? snapshot.stock_rows.map(([shape, ...values]) =>
      Object.fromEntries(snapshot.stock_fields[shape].map((key, i) => [key, values[i]])));
    for (const stock of stocks) {
      if (stock.date !== snapshot.date || !stockTicker.test(stock.ticker) || stock.currency !== "KRW" || !positive(stock.price)) continue;
      if (!quotes.has(stock.ticker)) quotes.set(stock.ticker, []);
      quotes.get(stock.ticker).push([dayNumber(stock.date), stock.price]);
    }
  }
  return quotes;
}

export async function publishKoreanPriceIndex(historyDirectory, sectorDirectory, output = join(historyDirectory, "korea-daily")) {
  const quotes = await readObservedQuotes(sectorDirectory);
  const files = new Map();
  for (const file of (await readdir(historyDirectory)).sort()) {
    const match = stockFile.exec(file);
    if (match && (!files.has(match[1]) || match[2])) files.set(match[1], file);
  }

  const tickers = [], curves = [], days = new Set();
  function addCurve(points, field) {
    if (!points.length) return null;
    for (const point of points) days.add(point[0]);
    const id = curves.length;
    curves.push({ points, field, next: 0 });
    return id;
  }
  for (const ticker of [...new Set([...files.keys(), ...quotes.keys()])].sort()) {
    const file = files.get(ticker);
    const value = file ? JSON.parse(gunzipSync(await readFile(join(historyDirectory, file)))) : null;
    if (value && (value.ticker !== ticker || value.currency !== "KRW")) throw new Error(`Invalid Korean price history for ${ticker}`);
    const prices = value ? readCurve(value) : [];
    const primary = addCurve(prices, 2);
    const prior = (value?.prior_snapshots ?? [])
      .filter(curve => curve.complete_history && curve.ticker === ticker && curve.currency === "KRW")
      .map(curve => addCurve(readCurve(curve), 2)).filter(id => id !== null);
    const recentPrices = quotes.get(ticker) ?? [];
    const observed = addCurve(recentPrices, 1);
    if (primary !== null || prior.length || observed !== null) tickers.push([ticker, primary, prior, observed, quoteScale(prices, recentPrices)]);
  }

  await mkdir(output, { recursive: true });
  const seriesKey = createHash("sha256").update(JSON.stringify(tickers)).digest("hex");
  const revision = createHash("sha256").update(seriesKey);
  const dates = [];
  for (const day of [...days].sort((a, b) => a - b)) {
    const date = isoDay(day);
    dates.push(date);
    const rows = curves.map(curve => {
      const { points, field } = curve;
      while (curve.next < points.length && points[curve.next][0] <= day) curve.next++;
      const last = points[curve.next - 1];
      return last ? [day - last[0], last[field]] : null;
    });
    const bytes = gzipSync(JSON.stringify({ key: seriesKey, date, rows }), { level: 4 });
    revision.update(bytes);
    await writeFile(join(output, `${date}.json.gz`), bytes);
  }
  await saveSectorFile(join(output, "index.json"), JSON.stringify({ version: 1, key: seriesKey, revision: revision.digest("hex"), count: curves.length, dates, tickers }) + "\n");
  const retained = new Set(dates.map(date => `${date}.json.gz`));
  for (const name of await readdir(output)) {
    if (dailyFile.test(name) && !retained.has(name)) await unlink(join(output, name));
  }
  return dates.length;
}
