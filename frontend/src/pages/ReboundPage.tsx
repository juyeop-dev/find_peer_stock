import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { TurnoverCalendar } from "../components/TurnoverCalendar";
import { DataRefreshStatus } from "../components/DataRefreshStatus";
import { ErrorNotice } from "../components/ErrorNotice";
import { LoadingSpinner } from "../components/LoadingSpinner";
import { calendarStockLink } from "../dataClient/stockDetailLinks";
import { usePollingData } from "../dataClient/usePollingData";
import { formatDateTime } from "../dataClient/formatters";
import { getReboundIndex, getReboundReport, REBOUND_BOARDS, REBOUND_RULES, reboundDateLabel, reboundEntries, reboundMessage, reboundPercent, reboundPrice, validReboundDate } from "../dataClient/reboundClient";
import "../styles/turnover.css";
import "../styles/rebounds.css";

export function ReboundPage() {
  const [params, setParams] = useSearchParams(), [month, setMonth] = useState(""), [query, setQuery] = useState(""), [copyStatus, setCopyStatus] = useState("");
  const { data: index, error: indexError, loading: indexLoading, refreshing: indexRefreshing, lastCheckedAt, refresh: refreshIndex } = usePollingData(getReboundIndex);
  const today = new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Seoul" }).format(new Date());
  const reports = useMemo(() => [...(index?.reports ?? [])].sort((a, b) => b.date.localeCompare(a.date)), [index]);
  const requested = params.get("date"), invalidDate = requested !== null && !validReboundDate(requested);
  const date = validReboundDate(requested) ? requested : reports[0]?.date ?? today;
  const hasReport = !invalidDate && reports.some(row => row.date === date);
  const load = useCallback((signal: AbortSignal) => getReboundReport(date, signal), [date]);
  const { data: loaded, error, loading, refreshing, refresh } = usePollingData(hasReport ? load : null);
  const report = hasReport && loaded?.date === date ? loaded : null;
  const closedDates = useMemo(() => new Map((index?.closures ?? []).map(row => [row.date, row.reason])), [index]);
  const days = useMemo(() => Object.fromEntries(reports.map(row => [row.date, row.count])), [reports]);
  const closed = !hasReport && ([0, 6].includes(new Date(`${date}T00:00:00Z`).getUTCDay()) || closedDates.has(date));
  useEffect(() => { setMonth(date.slice(0, 7)); setCopyStatus(""); }, [date]);
  const selectDate = (value: string) => { setParams({ date: value }); setQuery(""); };
  return <main className="pageShell turnoverPage reboundPage">
    <header className="turnoverHeader"><div><p className="eyebrow">DAILY REBOUND</p><h1>국내 대형주 반등</h1><p>당일 저가에서 종가까지, 얼마나 반등했는지 거래일별로 확인하세요.</p></div></header>
    <DataRefreshStatus cadence="rebounds" refreshing={indexRefreshing || refreshing} lastCheckedAt={lastCheckedAt} lastSourceAt={report?.source_metadata.fetched_at} onRefresh={async () => { await refreshIndex(); await refresh(); }} />
    {indexError && <ErrorNotice message={indexError} />}{indexLoading && !index && <LoadingSpinner />}
    {index && <div className="turnoverLayout"><aside className="turnoverSidebar">
      <div className="turnoverScope"><span className="eyebrow">조회 시장</span><strong>🇰🇷 KOSPI · KOSDAQ</strong><p>장 마감 일봉 기준 · Asia/Seoul</p></div>
      <TurnoverCalendar month={month || date.slice(0, 7)} selectedDate={date} today={today} days={days} closedDates={closedDates} onMonthChange={setMonth} onSelectDate={selectDate} recordLabel="반등 종목" />
      <div className="turnoverArchiveMeta"><label>달 바로 이동<input type="month" aria-label="반등 조회 월" value={month || date.slice(0, 7)} onChange={event => { if (validReboundDate(`${event.target.value}-01`)) setMonth(event.target.value); }} /></label><p><strong>{reports.length}일</strong>의 반등 기록이 저장되어 있어요.</p>{reports[0] && <><p>{reports.at(-1)?.date} ~ {reports[0].date}</p><button type="button" onClick={() => { setParams({}); setQuery(""); }}>최신 기록 · {reports[0].date}</button></>}</div>
    </aside><section className="turnoverReport" aria-busy={loading}>
      <div className="turnoverReportHeading"><div><p className="eyebrow">당일 저가 대비 종가 반등률</p><h2>{reboundDateLabel(date)}</h2></div><span className={hasReport ? "isRecorded" : closed ? "isClosed" : ""}>{hasReport ? `${report?.entries.length ?? reports.find(row => row.date === date)?.count}종목` : closed ? "휴장" : "미등록"}</span></div>
      <div className="reboundRules">{REBOUND_BOARDS.map(board => <div key={board}><strong>{board}</strong><span>시총 {board === "KOSPI" ? 5 : 1}조원 이상 · 반등 {REBOUND_RULES[board].rebound_min}% 이상</span></div>)}<p>전일 대비 하락 종목 제외 · 보합 포함 · 반등률 내림차순</p></div>
      {invalidDate && <ErrorNotice message="조회 날짜가 올바르지 않습니다. 달력에서 날짜를 선택해 주세요." />}
      {error && <ErrorNotice message={error} />}{loading && <LoadingSpinner />}
      {!invalidDate && !hasReport && <div className="turnoverEmpty"><strong>{closed ? "국내 시장 휴장일입니다." : "이 날짜의 반등 기록이 아직 없습니다."}</strong><p>{closed ? closedDates.get(date) ?? "주말에는 새 반등 기록을 만들지 않습니다." : "장 마감 후 수집된 거래일을 달력에서 선택해 주세요."}</p></div>}
      {index.refresh.status !== "updated" && <p role="status" className="semiFootnote">{index.refresh.status === "error" ? "최근 반등 수집에 실패했습니다. 저장된 거래일의 기록은 계속 조회할 수 있습니다." : index.refresh.message}</p>}
      {report && <>
        <div className="reboundToolbar"><input aria-label="반등 종목 검색" type="search" placeholder="종목명 · 종목코드 검색" value={query} onChange={event => setQuery(event.target.value)} /><button type="button" onClick={async () => { try { await navigator.clipboard.writeText(reboundMessage(report)); setCopyStatus("전체 반등 목록을 복사했습니다."); } catch { setCopyStatus("복사하지 못했습니다. 브라우저의 클립보드 권한을 확인해 주세요."); } }}>반등 목록 복사</button></div><p className="semiFootnote" role="status">{copyStatus}</p>
        {REBOUND_BOARDS.map(board => { const all = reboundEntries(report, board), entries = reboundEntries(report, board, query); return <section key={board} className={`reboundBoard ${board.toLowerCase()}`} aria-label={`${board} 반등 종목`}><h3><i aria-hidden="true" />{board} <span>({all.length})</span></h3>
          {query.trim() && <p className="semiFootnote">검색 결과 {entries.length}개 / 전체 {all.length}개</p>}
          {entries.length ? <ul>{entries.map(row => <li key={row.ticker}><div className="reboundStock"><Link to={calendarStockLink(row.ticker, "rebounds", "korea", date, `/rebounds?${new URLSearchParams({ date })}`)}>{row.name}</Link><small>{row.ticker}</small></div><div className="reboundReturn"><strong>{reboundPercent(row.rebound_pct)}</strong><span>{reboundPrice(row.price)} <b className={row.change_pct > 0 ? "semiUp" : ""}>({reboundPercent(row.change_pct)})</b></span></div><p className="reboundContext">당일 저가 {reboundPrice(row.low)} · 시총 {(row.market_cap / 1e12).toLocaleString("ko-KR", { maximumFractionDigits: 2 })}조원</p></li>)}</ul> : <p className="reboundEmpty">{query.trim() ? "검색 조건에 맞는 종목이 없습니다." : "이 시장에 선별 조건을 충족한 종목이 없습니다."}</p>}
        </section>; })}
        <p className="semiFootnote">반등률 = (종가 ÷ 당일 저가 − 1) × 100. 괄호 안 수치는 전일 대비 종가 등락률입니다. 표시 전 원래 수치로 선별하며, 시가총액·저가·종가·등락률을 확인할 수 없는 종목은 제외합니다. ETF·우선주·KONEX는 포함하지 않습니다.</p>
        {report.source_metadata.note && <p className="semiFootnote">{report.source_metadata.note}</p>}
        <div className="turnoverSources"><span>원본 수집 {formatDateTime(report.source_metadata.fetched_at)} · 전체 {report.source_metadata.scanned_symbols.toLocaleString("ko-KR")}개 조회</span>{report.sources.map(source => <a key={source.url} href={source.url} target="_blank" rel="noreferrer">{source.label} ↗</a>)}</div>
      </>}
    </section></div>}
  </main>;
}
