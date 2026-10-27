import assert from "node:assert/strict";
import test from "node:test";
import { parseInvestorFlow,parseInvestorIndex,investorRecord,investorSnapshot } from "../src/investors.js";
import { handle } from "../src/worker.js";

const item=(code,buy,sell)=>({investorGubun:code,buyPrice:String(buy*1e8),sellPrice:String(sell*1e8),diffValue:String((buy-sell)*1e8)});
const row=()=>({bizdate:"20240102",netAmounts:[item("8000",200,100),item("9000",50,110),item("9001",5,15),item("1000",100,130),item("7100",0,0)]});
const index=date=>({localTradedAt:date,closePrice:"100.25",compareToPreviousClosePrice:"2.25",fluctuationsRatio:"2.2",compareToPreviousPrice:{code:"5"}});
const json=data=>new Response(JSON.stringify(data),{headers:{"Content-Type":"application/json"}});
const request=body=>new Request("https://worker.example/refresh",{method:"POST",headers:{"Content-Type":"application/json",Origin:"https://juyeop-dev.github.io"},body:JSON.stringify(body)});
test("foreigners include other foreigners, institutions aggregate components, and zero is preserved",()=>{
  const value=parseInvestorFlow(row());
  assert.equal(value.date,"2024-01-02");
  assert.equal(value.investors.find(row=>row.key==="foreign").net,-70e8);
  assert.equal(value.investors.find(row=>row.key==="institution").net,-30e8);
  assert.equal(value.investors.find(row=>row.key==="other").net,0);
  assert.equal(value.investors.reduce((sum,row)=>sum+row.net,0),0);
});
test("malformed amounts, repeated groups, missing groups and unbalanced totals cannot be published",()=>{
  for(const modify of [r=>r.netAmounts[0].buyPrice="not a number",r=>r.netAmounts.push(r.netAmounts[0]),r=>r.netAmounts.shift(),r=>r.netAmounts[0].diffValue="999999999999",r=>r.bizdate="20240230"]) {
    const value=row();modify(value);assert.throws(()=>parseInvestorFlow(value));
  }
});
test("index decline signs are preserved and another day's index cannot be paired with a flow",()=>{
  const value=parseInvestorIndex(index("2024-01-02"));assert.equal(value.change,-2.25);assert.equal(value.change_pct,-2.2);
  assert.throws(()=>investorRecord("2024-01-02",[{date:"2024-01-02",index:{date:"2024-01-03"}}]));
  assert.throws(()=>investorRecord("2099-01-01",[]));
});
test("manual refresh queries both original markets and pairs exact dates even when the source ignores date parameters",async()=>{
  const calls=[];
  const fetcher=async(url,options)=>{calls.push({url,options});return json(url.includes('/trend/daily')?{content:[row()]}:[index("2024-01-02")]);};
  const value=await investorSnapshot("2024-01-02",fetcher);
  assert.equal(value.date,"2024-01-02");assert.equal(value.markets.length,2);assert.equal(calls.length,4);
  assert.ok(calls.every(call=>call.options.cf.cacheTtl===0));
  assert.ok(calls.some(call=>call.url.includes("marketType=KOSPI"))&&calls.some(call=>call.url.includes("marketType=KOSDAQ")));
});
test("invalid requests are rejected before source access and missing selected dates never fall back to latest",async()=>{
  let calls=0;
  const fetcher=async(url)=>{calls++;return json(url.includes('/trend/daily')?{content:[row()]}:[index("2024-01-02")]);};
  for(const date of ["2024-02-30","2022-12-29","2099-01-01",123])assert.equal((await handle(request({kind:"investors",date}),{},fetcher)).status,400);
  assert.equal(calls,0);
  const response=await handle(request({kind:"investors",date:"2024-01-03"}),{},fetcher);
  assert.equal(response.status,502);
});
