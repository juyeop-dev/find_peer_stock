import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import ts from 'typescript';
const source = await readFile(new URL('../src/dataClient/chartAnalysis.ts', import.meta.url), 'utf8');
const js = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText;
const { exponentialAverage, bollingerBands, relativeStrength, macd, fibonacciLevels, parseAnalysisPreferences } = await import(`data:text/javascript;base64,${Buffer.from(js).toString('base64')}`);
const points = values => values.map((value, i) => ({ date: new Date(Date.UTC(2024, 0, i + 1)).toISOString().slice(0, 10), value }));
const near = (a, b) => assert.ok(Math.abs(a - b) < 1e-8, `${a} != ${b}`);

test('EMA seeds a complete SMA and remains causal when future sessions are appended', () => {
  assert.deepEqual(exponentialAverage(points([10, 20]), 3), []);
  assert.deepEqual(exponentialAverage(points([10, 20, 30, 50]), 3).map(p => p.value), [20, 35]);
  const prefix = exponentialAverage(points([10, 20, 30, 50]), 3);
  assert.deepEqual(exponentialAverage(points([10, 20, 30, 50, 999]), 3).slice(0, 2), prefix);
});
test('Bollinger uses population deviation and never a partial window', () => {
  const bands = bollingerBands(points([1, 2, 3, 4]), 3, 2);
  assert.deepEqual(bands.middle.map(p => p.value), [2, 3]);
  near(bands.upper[0].value, 2 + 2 * Math.sqrt(2 / 3));
  near(bands.lower[0].value, 2 - 2 * Math.sqrt(2 / 3));
  assert.equal(bands.upper[0].date, '2024-01-03');
});
test('Wilder RSI has independent reference values and handles flat, rising, falling prices', () => {
  const closes = [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08, 45.89, 46.03, 45.61, 46.28, 46.28, 46.00];
  const rsi = relativeStrength(points(closes));
  near(rsi[0].value, 70.46413502109705); near(rsi[1].value, 66.24961855355505);
  assert.equal(relativeStrength(points(Array(20).fill(100)))[0].value, 50);
  assert.equal(relativeStrength(points(Array.from({ length: 20 }, (_, i) => i + 1)))[0].value, 100);
  assert.equal(relativeStrength(points(Array.from({ length: 20 }, (_, i) => 100 - i)))[0].value, 0);
});
test('MACD requires warm-up, aligns signal dates, and gives the expected steady linear slope', () => {
  const data = points(Array.from({ length: 50 }, (_, i) => i + 1)), result = macd(data);
  assert.equal(result.line[0].date, data[25].date); assert.equal(result.signal[0].date, data[33].date);
  for (const p of result.line) near(p.value, 7);
  for (const p of result.signal) near(p.value, 7);
  for (const p of result.histogram) near(p.value, 0);
  assert.deepEqual(macd(data.slice(0, 25)), { line: [], signal: [], histogram: [] });
  assert.deepEqual(macd([...data, { date: '2024-02-20', value: 999 }]).line.slice(0, result.line.length), result.line);
});
test('Fibonacci preserves anchor direction and restores only supported preferences', () => {
  const levels = fibonacciLevels({ date: '2024-01-01', value: 100 }, { date: '2024-01-02', value: 200 });
  assert.equal(levels[0].value, 200); assert.equal(levels.at(-1).value, 100); near(levels.find(p => p.ratio === .618).value, 138.2);
  const saved = parseAnalysisPreferences(JSON.stringify({ studies: ['rsi', 'script', 'rsi'], averages: [20, 999], width: 99, kind: 'area', grid: false }));
  assert.deepEqual(saved, { studies: ['rsi'], averages: [20], width: 2, kind: 'area', grid: false, dashed: false });
  assert.deepEqual(parseAnalysisPreferences('{bad'), parseAnalysisPreferences(null));
});
