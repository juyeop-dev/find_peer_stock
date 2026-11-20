import React from "react";
import {createRoot} from "react-dom/client";
import {StockHistoryChart} from "../src/components/StockHistoryChart";
import {CreditBalancePage} from "../src/pages/CreditBalancePage";
import {getPublishedStockHistory} from "../src/dataClient/stockHistoryClient";
import "../src/styles/global.css";
import "../src/styles/semiconductor.css";
import "../src/styles/stockChartWorkspace.css";

const prices: [string, number, number][] = [["2013-12-30", 70, 70], ["2014-01-02", 71, 71], ["2014-12-30", 80, 80]];
for (let index = 400; index > 0; index--) {
  const day = new Date(Date.now() - index * 86400000);
  if (![0, 6].includes(day.getUTCDay())) prices.push([day.toISOString().slice(0, 10), 100 + (400 - index) / 10, 100 + (400 - index) / 10]);
}
const credit = {generated_at: new Date().toISOString(), latest_date: prices.at(-1)![0], unit: "KRW million", metric: "margin loan balance",
  source: "검증용 표본", source_url: "https://example.invalid/fixture", history: prices.map(([date, close]) => ({date, total: close * 100000, kospi: close * 60000, kosdaq: close * 40000}))};
const original = window.fetch.bind(window);
window.fetch = async (input, init) => {
  const url = new URL(typeof input === "string" ? input : input instanceof URL ? input.href : input.url, location.href);
  if (new URLSearchParams(location.search).has("remote")) {
    if (["127.0.0.1", "localhost"].includes(url.hostname)) return original(input, init);
    return new Response("fixture only", {status: 404});
  }
  if (url.pathname.includes("/data/stock-history/")) return Response.json({ticker: "TEST", currency: "USD", source: "검증용 표본", fetched_at: new Date().toISOString(), prices});
  if (url.pathname.includes("/data/credit/")) return Response.json(credit);
  if (url.pathname.includes("/data/chart-catalog")) return Response.json([{ticker: "TEST", name: "검증 종목", exchange: "NASDAQ", market: "us"}]);
  if (url.origin !== location.origin || url.pathname.includes("/data/")) return new Response("fixture only", {status: 404});
  return original(input, init);
};
Object.assign(window, {readPublishedFixture: () => getPublishedStockHistory("TEST")});
createRoot(document.getElementById("root")!).render(<>
  <header style={{padding: 20}}><h1>연도 설정 연결 검증</h1><p>이 화면의 가격·잔고는 자동 검증용 표본입니다.</p></header>
  <main className="pageShell semiPage"><StockHistoryChart ticker="TEST" name="검증 종목" exchange="NASDAQ" /></main>
  <CreditBalancePage />
</>);
