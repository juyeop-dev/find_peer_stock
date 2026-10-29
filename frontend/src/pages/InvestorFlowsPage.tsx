import { useCallback, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { SectorCalendar } from "../components/SectorCalendar";
import { DataRefreshStatus } from "../components/DataRefreshStatus";
import { ErrorNotice } from "../components/ErrorNotice";
import { LoadingSpinner } from "../components/LoadingSpinner";
import { getInvestorData, investorMoney, investorTotals, INVESTOR_MARKETS, validInvestorDate } from "../dataClient/investorDataClient";
import { usePollingData } from "../dataClient/usePollingData";
import { formatDateTime } from "../dataClient/formatters";
import { formatPercent } from "../dataClient/semiconductorMath";
import "../styles/sectorRankings.css";
import "../styles/investors.css";

const tone=(value: number)=>value>0?"semiUp":value<0?"semiDown":"";
const marketName=(value: string)=>value==="KOSPI"?"코스피":value==="KOSDAQ"?"코스닥":"전체";
export function InvestorFlowsPage() {
  const [params,setParams]=useSearchParams(), [viewMonth,setViewMonth]=useState("");
  const requested=params.get("date")??"", market=INVESTOR_MARKETS.some(value=>value.key===params.get("market"))?params.get("market")!:"all";
  const load=useCallback((signal: AbortSignal,fromSource=false)=>getInvestorData(signal,fromSource,requested),[requested]);
  const {data,loading,error,refreshing,lastCheckedAt,lastSourceAt,refresh}=usePollingData(load,300000);
  const selectedDate=requested||data?.latest_date||"", selected=data?.history.find(row=>row.date===selectedDate);
  const month=viewMonth||(validInvestorDate(selectedDate)?selectedDate.slice(0,7):data?.latest_date.slice(0,7))||"";
  function change(key: string,value: string) {const next=new URLSearchParams(params);value?next.set(key,value):next.delete(key);setParams(next,{replace:true});}
  const selectDate=(date: string)=>{setViewMonth(date.slice(0,7));change("date",date);};
  const totals=selected?investorTotals(selected,market):[];
  const rows=data?.history.filter(row=>row.date.startsWith(month)).slice().reverse()??[];
  const markets=selected?.markets.filter(row=>market==="all"||row.market===market)??[];
  return <main className="pageShell semiPage investorPage">
    <header className="semiHero"><div><p className="eyebrow">DAILY INVESTOR FLOWS</p><h1>투자자별 매매동향</h1><p>개인·외국인·기관이 얼마나 사고팔았는지, 같은 거래일의 코스피·코스닥 지수와 함께 확인하세요.</p></div></header>
    <DataRefreshStatus cadence="investors" generatedAt={data?.generated_at} refreshing={refreshing} lastCheckedAt={lastCheckedAt} lastSourceAt={lastSourceAt} onRefresh={refresh} />
    {loading&&<LoadingSpinner />}{error&&<ErrorNotice message={error} />}
    {data&&<>
      <div className="investorToolbar"><div className="semiPeriodTabs" aria-label="조회 시장">{INVESTOR_MARKETS.map(value=><button key={value.key} className={market===value.key?"active":""} aria-pressed={market===value.key} onClick={()=>change("market",value.key)}>{value.label}</button>)}</div><span>최신 거래일 {data.latest_date} · 금액 단위: 억원 · KRX 시장</span></div>
      {month&&<SectorCalendar month={month} selectedDate={selectedDate} latestDate={data.latest_date} records={data.history.map(row=>({date:row.date,fetched_at:row.fetched_at,count:row.markets.length,industries:0}))} onMonthChange={setViewMonth} onSelectDate={selectDate} onLatest={()=>{setViewMonth(data.latest_date.slice(0,7));change("date","");}} title="투자자 수급 캘린더" description="날짜를 선택하면 해당 거래일의 매매 금액과 지수가 함께 바뀝니다." ariaLabel="투자자 매매 조회 날짜 선택" footnote="2022년 이후 실제 자료가 있는 거래일만 선택할 수 있습니다. 휴장일·미제공 날짜는 비활성화됩니다." recordLabel={record=>`${record.date} 코스피·코스닥 매매 기록`} recordText={record=>data.history.find(row=>row.date===record.date)?.status==="provisional"?"집계중":"마감"} />}
      {!selected?<ErrorNotice message="선택한 날짜의 매매 기록이 없습니다. 캘린더에서 거래일을 선택해 주세요." />:<>
        <div className="investorDateHeading"><h2>{selected.date} · {marketName(market)} 매매 현황</h2><span className={`investorStatus ${selected.status}`}>{selected.status==="provisional"?"잠정 · 집계중":"마감 기록"}</span></div>
        {selected.status==="provisional"&&<p className="investorProvisional" role="status">현재 거래일의 잠정 집계입니다. 마감 후에도 제공처 정정으로 값이 달라질 수 있습니다.</p>}
        <div className="investorIndices" aria-label="선택한 날짜의 시장 지수">{selected.markets.map(row=><button key={row.market} className={market===row.market?"active":""} aria-pressed={market===row.market} onClick={()=>change("market",row.market)}><span>{marketName(row.market)} 지수</span><strong>{row.index.close.toLocaleString("ko-KR",{minimumFractionDigits:2,maximumFractionDigits:2})}<small>pt</small></strong><b className={tone(row.index.change_pct??0)}>{row.index.change===null?"—":`${row.index.change>0?"+":""}${row.index.change.toFixed(2)}pt`} ({formatPercent(row.index.change_pct)})</b><small>{row.index.date} · 전 거래일 종가 대비</small></button>)}</div>
        <section className="investorSummary" aria-label="투자자별 매수 매도 요약">{totals.filter(row=>row.key!=="other").map(row=><article key={row.key}><h3>{row.name}</h3><span>순매수</span><strong className={tone(row.net)}>{investorMoney(row.net,true)}<small>억원</small></strong><dl><div><dt>매수</dt><dd>{investorMoney(row.buy)}</dd></div><div><dt>매도</dt><dd>{investorMoney(row.sell)}</dd></div></dl></article>)}</section>
        <section className="semiPanel"><div className="semiPanelHeading"><h2>시장별 투자자 매매</h2><p>{selected.date} 기준 · 매수−매도는 순매수, 음수는 순매도입니다. 단위: 억원</p></div><div className="semiTableWrap"><table className="semiTable investorFlowTable"><thead><tr><th scope="col">시장</th><th scope="col">투자자</th><th scope="col" className="semiNumber">매수 금액</th><th scope="col" className="semiNumber">매도 금액</th><th scope="col" className="semiNumber">순매수 금액</th><th scope="col">매매 방향</th></tr></thead><tbody>{markets.flatMap(value=>value.investors.map(row=><tr key={`${value.market}:${row.key}`} data-market={value.market} data-investor={row.key}><td>{marketName(value.market)}</td><th scope="row">{row.name}</th><td className="semiNumber">{investorMoney(row.buy)}</td><td className="semiNumber">{investorMoney(row.sell)}</td><td className={`semiNumber ${tone(row.net)}`}>{investorMoney(row.net,true)}</td><td className={tone(row.net)}>{row.net>0?"순매수":row.net<0?"순매도":"균형"}</td></tr>))}</tbody></table></div>
          <p className="semiFootnote">외국인은 기타외국인을 포함합니다. 기관은 금융투자·보험·투신·사모·은행·기타금융·연기금 등 기관 분류의 합계입니다. 기타법인 등은 별도로 표시합니다. 전체 요약은 두 시장의 금액을 합산합니다.</p>
          <details className="investorDetails"><summary>기관·외국인 등 세부 분류 보기</summary><div className="semiTableWrap"><table className="semiTable"><thead><tr><th scope="col">시장</th><th scope="col">분류</th><th scope="col" className="semiNumber">매수</th><th scope="col" className="semiNumber">매도</th><th scope="col" className="semiNumber">순매수</th></tr></thead><tbody>{markets.flatMap(value=>value.details.map(row=><tr key={`${value.market}:${row.code}`}><td>{marketName(value.market)}</td><th scope="row">{row.name}</th><td className="semiNumber">{investorMoney(row.buy)}</td><td className="semiNumber">{investorMoney(row.sell)}</td><td className={`semiNumber ${tone(row.net)}`}>{investorMoney(row.net,true)}</td></tr>))}</tbody></table></div></details>
        </section>
      </>}
      <section className="semiPanel"><div className="semiPanelHeading"><h2>{month} 일별 기록</h2><p>{marketName(market)} 투자자 순매수 · 단위: 억원 · 날짜를 누르면 상세 현황을 봅니다.</p></div><div className="semiTableWrap"><table className="semiTable investorHistoryTable"><thead><tr><th scope="col">거래일</th><th scope="col" className="semiNumber">코스피 지수</th><th scope="col" className="semiNumber">코스닥 지수</th><th scope="col" className="semiNumber">개인 순매수</th><th scope="col" className="semiNumber">외국인 순매수</th><th scope="col" className="semiNumber">기관 순매수</th></tr></thead><tbody>{rows.map(day=>{const sum=investorTotals(day,market);return <tr key={day.date} className={selectedDate===day.date?"selected":""}><th scope="row"><button className="semiTextButton" onClick={()=>selectDate(day.date)}>{day.date}</button></th>{["KOSPI","KOSDAQ"].map(key=><td className="semiNumber" key={key}>{day.markets.find(value=>value.market===key)!.index.close.toLocaleString("ko-KR",{minimumFractionDigits:2,maximumFractionDigits:2})}</td>)}{sum.filter(row=>row.key!=="other").map(row=><td key={row.key} className={`semiNumber ${tone(row.net)}`}>{investorMoney(row.net,true)}</td>)}</tr>;})}</tbody></table></div>{!rows.length&&<p className="semiEmpty">이 달에 제공된 기록이 없습니다.</p>}</section>
      <p className="semiFootnote">자료: <a href={data.source_url} target="_blank" rel="noreferrer">{data.source}</a>. KRX 거래 자료이며 NXT 거래는 포함하지 않습니다. 지수는 해당 거래일의 제공값이며 장중에는 잠정값입니다. 원본 매매 금액의 반올림으로 매수−매도와 순매수에 차이가 있을 수 있습니다. {selected?`선택 기록 조회 ${formatDateTime(selected.fetched_at)} · `:""}기록 {data.history.length}개 거래일. 제공처 발표·정정 시차가 있을 수 있습니다.</p>
    </>}
  </main>;
}
