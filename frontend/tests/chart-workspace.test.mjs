import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import test from 'node:test';
import ts from 'typescript';
async function load(path) {
  const source=await readFile(new URL(path,import.meta.url),'utf8');
  const js=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
  return import(`data:text/javascript;base64,${Buffer.from(js).toString('base64')}`);
}
const {compareHistories,movingAverage,clampWindow,zoomWindow,parseDrawings,drawingStorageKey,nearestDate,channelSegments,measureChange}=await load('../src/dataClient/chartWorkspace.ts');
const {searchChartSymbols}=await load('../src/dataClient/chartComparisonClient.ts');
const point=(date,close,adjusted_close=close)=>({date,close,adjusted_close,volume:null});
const base={ticker:'BASE',name:'Base',currency:'KRW',color:'#000000',history:[point('2026-01-02',100),point('2026-01-05',50,100),point('2026-01-06',55,110),point('2026-01-07',60,120)]};

test('comparison uses the same observed dates and adjusted-price baseline across currencies without inventing holiday prices',()=>{
  const other={ticker:'OTHER',name:'Other',currency:'USD',color:'#123456',history:[point('2026-01-05',200),point('2026-01-07',240)]};
  const value=compareHistories(base,[other],'2026-01-02','2026-01-07');
  assert.equal(value.start,'2026-01-05');
  for(const row of value.series) {
    assert.deepEqual(row.points.map(p=>p.date),['2026-01-05','2026-01-07']);
    assert.equal(row.points[0].value,0);assert.ok(Math.abs(row.points[1].value-20)<1e-10);
  }
  assert.equal(base.history[1].close,50);
});
test('a later listing starts at its first common session; fewer than two observations produces no comparison',()=>{
  const recent={...base,ticker:'IPO',history:[point('2026-01-06',10),point('2026-01-07',11)]};
  assert.equal(compareHistories(base,[recent],'2026-01-02','2026-01-07').start,'2026-01-06');
  assert.deepEqual(compareHistories(base,[recent],'2026-01-02','2026-01-06'),{start:null,series:[]});
  assert.equal(compareHistories(base,[],'2026-01-02','2026-01-05').series[0].points[1].value,0);
});
test('moving averages use preceding observed sessions, never a partial window or calendar-day fills',()=>{
  assert.deepEqual(movingAverage(base.history,3),[{date:'2026-01-06',value:205/3},{date:'2026-01-07',value:55}]);
  assert.deepEqual(movingAverage(base.history,20),[]);
  assert.deepEqual(movingAverage(base.history,0),[]);
});
test('zoom and pan windows stay within the available history and preserve a useful minimum',()=>{
  for(const count of [0,1,2,7,10,40,2000]) for(const start of [-200,0,10,1500]) {
    const value=clampWindow(start,start+40,count);
    assert.ok(value[0]>=0&&value[1]>=value[0]&&value[1]<=Math.max(0,count-1));
    for(const factor of [.1,.8,1.5,20]) {
      const zoomed=zoomWindow(value,count,factor,.75);
      assert.ok(zoomed[0]>=0&&zoomed[1]>=zoomed[0]&&zoomed[1]<=Math.max(0,count-1));
    }
  }
  assert.deepEqual(clampWindow(30,50,100),[30,50]);
  assert.deepEqual(zoomWindow([0,99],100,.5,0),[0,50]);
});
test('drawings validate untrusted storage and retain date/price coordinates separately by listing and comparison basis',()=>{
  const valid={id:'one',type:'trend',scale:'price',start:{date:'2026-01-02',value:100},end:{date:'2026-01-07',value:120},color:'#123456'};
  assert.deepEqual(parseDrawings(JSON.stringify([valid,{...valid,color:'url(https://invalid)'},{...valid,start:null},{...valid,type:'script'}])),[valid]);
  assert.deepEqual(parseDrawings('{broken'),[]);assert.deepEqual(parseDrawings('{}'),[]);
  assert.equal(drawingStorageKey('aapl','price:USD'),drawingStorageKey('AAPL','price:USD'));
  assert.notEqual(drawingStorageKey('AAPL','price:USD'),drawingStorageKey('AAPL','percent:2026-01-02:MSFT'));
  assert.notEqual(drawingStorageKey('AAPL','price:USD'),drawingStorageKey('AMD','price:USD'));
});
test('date anchoring and symbol search preserve listing identity, Korean names, and exact ticker priority',()=>{
  assert.equal(nearestDate(['2026-01-02','2026-01-05','2026-01-06'],'2026-01-04'),1);
  assert.equal(nearestDate(['2026-01-02','2026-01-05'],'2020-01-01'),0);
  const rows=[{ticker:'000660.KS',name:'SK하이닉스',exchange:'KOSPI'},{ticker:'005930.KS',name:'삼성전자',exchange:'KOSPI'},{ticker:'AAPL',name:'Apple'},{ticker:'AAPL2',name:'Other'}];
  assert.equal(searchChartSymbols(rows,'하이닉스',[])[0].ticker,'000660.KS');
  assert.deepEqual(searchChartSymbols(rows,'AAPL',['AAPL2']).map(row=>row.ticker),['AAPL']);
  assert.equal(searchChartSymbols(rows,'aapl',[])[0].ticker,'AAPL');
});

test('parallel channels preserve the trend slope and put the middle line exactly halfway, including negative offsets',()=>{
  const trend={id:'trend',type:'trend',scale:'price',start:{date:'2026-01-02',value:100},end:{date:'2026-01-07',value:160},color:'#123456',channel:{offset:40,visible:true,middle:true}};
  const channel=channelSegments(trend);
  assert.deepEqual(channel.parallel,{start:{date:'2026-01-02',value:140},end:{date:'2026-01-07',value:200}});
  assert.deepEqual(channel.middle,{start:{date:'2026-01-02',value:120},end:{date:'2026-01-07',value:180}});
  assert.equal(channel.parallel.end.value-channel.parallel.start.value,trend.end.value-trend.start.value);
  assert.equal(channelSegments({...trend,channel:{...trend.channel,offset:-20}}).middle.start.value,90);
  assert.equal(channelSegments({...trend,channel:{...trend.channel,visible:false}}),null);
  assert.equal(channelSegments({...trend,type:'horizontal'}),null);
  assert.equal(trend.start.value,100);
});
test('legacy drawings and channel preferences restore without accepting malformed channel settings',()=>{
  const old={id:'one',type:'trend',scale:'price',start:{date:'2026-01-02',value:100},end:{date:'2026-01-07',value:120},color:'#123456'};
  const current={...old,channel:{offset:-25.25,visible:true,middle:false}};
  assert.deepEqual(parseDrawings(JSON.stringify([old,current,{...old,channel:{offset:'bad',visible:true,middle:true}}])),[old,current,old]);
});
test('reference measurement reports signed price returns and handles a zero or negative percentage-axis baseline correctly',()=>{
  assert.deepEqual(measureChange(100,120,'price'),{delta:20,percent:20});
  assert.deepEqual(measureChange(100,80,'price'),{delta:-20,percent:-20});
  assert.deepEqual(measureChange(0,10,'price'),{delta:10,percent:null});
  assert.deepEqual(measureChange(0,10,'percent'),{delta:10,percent:10});
  assert.deepEqual(measureChange(-50,-40,'percent'),{delta:10,percent:20});
  assert.deepEqual(measureChange(100,120,'percent'),{delta:20,percent:10});
  assert.equal(measureChange(-100,-90,'percent').percent,null);
});
