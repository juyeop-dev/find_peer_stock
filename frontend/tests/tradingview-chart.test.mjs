import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import test from 'node:test';
import ts from 'typescript';
const source=await readFile(new URL('../src/dataClient/tradingViewChart.ts',import.meta.url),'utf8');
const js=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const {tradingViewChartOptions,tradingViewChartUrl,tradingViewWidgetRestricted}=await import(`data:text/javascript;base64,${Buffer.from(js).toString('base64')}`);
test('official chart exposes drawing, comparison, intervals, indicators, image and data panels without substituting another listing',()=>{
  const value=tradingViewChartOptions('KRX:000660');
  assert.equal(value.symbol,'KRX:000660');assert.deepEqual(value.watchlist,['KRX:000660']);
  assert.equal(value.hide_side_toolbar,false);assert.equal(value.hide_top_toolbar,false);
  for(const key of ['allow_symbol_change','withdateranges','save_image','details','hotlist','show_popup_button'])assert.equal(value[key],true,key);
  assert.equal(value.locale,'kr');assert.equal(value.style,'1');
});
test('known KRX widget restriction selects a usable archive instead of presenting a broken embedded chart',()=>{
  assert.equal(tradingViewWidgetRestricted('KRX:000660'),true);
  assert.equal(tradingViewWidgetRestricted('NASDAQ:MU'),false);
  assert.equal(tradingViewWidgetRestricted(null),false);
});
test('full TradingView link preserves the exact exchange and safely encodes the symbol',()=>{
  const value=new URL(tradingViewChartUrl('NYSE:BRK.B'));
  assert.equal(value.origin,'https://www.tradingview.com');assert.equal(value.pathname,'/chart/');
  assert.equal(value.searchParams.get('symbol'),'NYSE:BRK.B');
  assert.equal(new URL(tradingViewChartUrl('A&B')).searchParams.get('symbol'),'A&B');
});
