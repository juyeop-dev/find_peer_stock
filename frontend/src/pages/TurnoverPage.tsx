import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ErrorNotice } from "../components/ErrorNotice";
import { LoadingSpinner } from "../components/LoadingSpinner";
import { TurnoverCalendar } from "../components/TurnoverCalendar";
import { getTurnoverIndex, getTurnoverReport } from "../dataClient/staticStockDataClient";
import { getExternalQuoteLink } from "../dataClient/externalLinks";
import { usePollingData } from "../dataClient/usePollingData";
import type { TurnoverEntry } from "../dataClient/turnoverTypes";
import "../styles/turnover.css";

function validDate(value: string | null): value is string {
  if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const parsed = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
}

function dateInTimezone(timezone: string): string {
  const parts = new Intl.DateTimeFormat("en", { timeZone: timezone, year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(new Date());
  return ["year", "month", "day"].map((type) => parts.find((part) => part.type === type)?.value).join("-");
}

function readableDate(value: string): string {
  return new Intl.DateTimeFormat("ko-KR", { timeZone: "UTC", year: "numeric", month: "long", day: "numeric", weekday: "long" }).format(new Date(`${value}T00:00:00Z`));
}

function formatMoney(value: number | null, currency: string): string {
  if (value == null) return "-";
  try {
    return new Intl.NumberFormat("ko-KR", { style: "currency", currency, maximumFractionDigits: currency === "KRW" || currency === "JPY" ? 0 : 2 }).format(value);
  } catch { return `${new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 2 }).format(value)} ${currency}`; }
}

function formatHundredMillions(value: number | null, currency: string, splitTrillions = false): string {
  if (value == null) return "-";
  const currencyNames: Record<string, string> = {
    KRW: "원", USD: "달러", JPY: "엔", TWD: "대만달러", CNY: "위안",
    EUR: "유로", GBP: "파운드", CHF: "스위스프랑"
  };
  const unit = currencyNames[currency] ?? currency;
  if (value < 100_000_000) {
    const tenThousands = Math.round(value / 10_000);
    return tenThousands === 0
      ? `1만 ${unit} 미만`
      : `${new Intl.NumberFormat("ko-KR").format(tenThousands)}만 ${unit}`;
  }
  const hundredMillions = Math.round(value / 100_000_000);
  if (splitTrillions && hundredMillions >= 10_000) {
    const trillions = Math.floor(hundredMillions / 10_000);
    const remainingHundredMillions = hundredMillions % 10_000;
    const trillionText = `${new Intl.NumberFormat("ko-KR").format(trillions)}조`;
    return remainingHundredMillions === 0
      ? `${trillionText} ${unit}`
      : `${trillionText} ${new Intl.NumberFormat("ko-KR").format(remainingHundredMillions)}억 ${unit}`;
  }
  return `${new Intl.NumberFormat("ko-KR").format(hundredMillions)}억 ${unit}`;
}

function changeText(value: number | null): string { return value == null ? "-" : `${value > 0 ? "+" : ""}${value.toFixed(2)}%`; }
function changeClass(value: number | null): string { return value == null || value === 0 ? "flat" : value > 0 ? "up" : "down"; }
function initials(entry: TurnoverEntry): string { return entry.name.replace(/[^\p{L}\p{N}]/gu, "").slice(0, 2).toUpperCase() || entry.ticker.slice(0, 2); }

export function TurnoverPage() {
  const [params, setParams] = useSearchParams();
  const { data: index, error: indexError, loading: indexLoading } = usePollingData(getTurnoverIndex);
  const [month, setMonth] = useState("");
  const [search, setSearch] = useState("");
  const market = index?.markets.find((item) => item.id === params.get("market"))
    ?? index?.markets.find((item) => item.id === "korea") ?? index?.markets[0];
  const marketId = market?.id ?? "korea";
  const reports = useMemo(() => (index?.reports ?? []).filter((item) => item.market === marketId)
    .sort((a, b) => b.date.localeCompare(a.date)), [index, marketId]);
  const today = dateInTimezone(market?.timezone ?? "Asia/Seoul");
  const selectedDate = validDate(params.get("date")) ? params.get("date")! : reports[0]?.date ?? today;
  const hasReport = reports.some((item) => item.date === selectedDate);
  const loadReport = useCallback((signal: AbortSignal) => getTurnoverReport(marketId, selectedDate, signal), [marketId, selectedDate]);
  const { data: loadedReport, error: reportError, loading: reportLoading } = usePollingData(hasReport ? loadReport : null);
  const report = loadedReport?.market === marketId && loadedReport.date === selectedDate ? loadedReport : null;
  useEffect(() => setMonth(selectedDate.slice(0, 7)), [selectedDate, marketId]);
  const query = search.trim().toLocaleLowerCase();
  const entries = (report?.entries ?? []).filter((entry) => [entry.name, entry.ticker, entry.sector, entry.industry]
    .join(" ").toLocaleLowerCase().includes(query));
  const days = useMemo(() => Object.fromEntries(reports.map((item) => [item.date, item.count])), [reports]);

  function selectDate(date: string) { setParams({ market: marketId, date }); setMonth(date.slice(0, 7)); }
  function selectMarket(id: string) { setParams({ market: id }); setSearch(""); }

  return <main className="pageShell turnoverPage">
    <header className="turnoverHeader"><div><p className="eyebrow">DAILY TURNOVER RANKING</p><h1>거래대금 캘린더</h1>
      <p>매 거래일 시장에서 거래대금이 가장 컸던 종목 1위부터 30위까지 확인하세요.</p></div></header>
    {indexError ? <ErrorNotice message={indexError} /> : null}
    {!index && indexLoading ? <LoadingSpinner /> : null}
    {index && market ? <>
      <div className="turnoverMarkets" role="group" aria-label="국가별 시장">
        {index.markets.map((item) => <button key={item.id} aria-pressed={marketId === item.id} onClick={() => selectMarket(item.id)}>
          {item.label}<span>{index.reports.some((record) => record.market === item.id) ? "기록 있음" : index.refresh?.[item.id]?.status === "unsupported" ? "수집 미지원" : "기록 대기"}</span>
        </button>)}
      </div>
      <div className="turnoverLayout">
        <aside className="turnoverSidebar">
          <div className="turnoverScope"><span className="eyebrow">조회 시장</span><strong>{market.label}</strong><p>장 마감 기준 · {market.timezone}</p></div>
          <TurnoverCalendar month={month || selectedDate.slice(0, 7)} selectedDate={selectedDate} today={today}
            days={days} onMonthChange={setMonth} onSelectDate={selectDate} />
          <div className="turnoverArchiveMeta"><label>달 바로 이동<input type="month" value={month || selectedDate.slice(0, 7)}
            onChange={(event) => validDate(`${event.target.value}-01`) && setMonth(event.target.value)} /></label>
            <p><strong>{reports.length}일</strong>의 순위가 저장되어 있어요.</p>
            {reports[0] ? <button onClick={() => setParams({ market: marketId })}>최신 순위 보기 · {reports[0].date}</button> : null}</div>
        </aside>
        <section className="turnoverReport" aria-busy={reportLoading}>
          <div className="turnoverReportHeading"><div><p className="eyebrow">{market.label} · 거래대금 TOP 30</p><h2>{readableDate(selectedDate)}</h2></div>
            <span className={hasReport ? "isRecorded" : ""}>{hasReport ? `${report?.entries.length ?? 30}종목` : "미등록"}</span></div>
          {reportLoading ? <LoadingSpinner /> : null}{reportError ? <ErrorNotice message={reportError} /> : null}
          {!hasReport ? <div className="turnoverEmpty"><strong>이 날짜의 거래대금 순위가 아직 없습니다.</strong><p>순위가 수집된 거래일을 달력에서 선택해 주세요.</p></div> : null}
          {report ? <>
            <div className="turnoverToolbar"><p>{report.summary}</p><input type="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="종목명 · 티커 · 산업 검색" aria-label="순위표 검색" /></div>
            <div className="turnoverTableWrap"><table className="turnoverTable"><thead><tr>
              <th>순위</th><th>종목명</th><th>현재가</th><th>등락률</th><th>거래대금</th><th>시가총액</th><th>산업</th>
            </tr></thead><tbody>{entries.map((entry) => {
              const quote = getExternalQuoteLink(entry.ticker);
              return <tr key={entry.ticker}><td className="turnoverRank"><strong>{entry.rank}</strong></td><td><a className="turnoverCompany" href={quote.href} target="_blank" rel="noreferrer" title={`${quote.label}에서 ${entry.name} 보기`}>
                <span className="turnoverLogo"><span>{initials(entry)}</span>{entry.logo_url ? <img src={entry.logo_url} alt="" loading="lazy" onError={(event) => { event.currentTarget.style.display = "none"; }} /> : null}</span>
                <span><strong>{entry.name}</strong><small>{entry.ticker} · {entry.exchange}</small></span></a></td>
                <td className="number">{formatMoney(entry.price, entry.currency)}</td><td className={`number change ${changeClass(entry.change_pct)}`}>{changeText(entry.change_pct)}</td>
                <td className="number turnoverValue"><strong>{formatHundredMillions(entry.turnover, entry.currency)}</strong></td><td className="number marketCapValue">{formatHundredMillions(entry.market_cap, entry.currency, true)}</td>
                <td><span className="turnoverIndustry"><strong>{entry.sector}</strong><small>{entry.industry}</small></span></td></tr>;
            })}</tbody></table></div>
            {entries.length === 0 ? <div className="turnoverEmpty compact"><strong>검색 결과가 없습니다.</strong><button onClick={() => setSearch("")}>검색 초기화</button></div> : null}
            {report.sources?.length ? <div className="turnoverSources"><strong>자료</strong>{report.sources.map((source) => source.url ? <a key={source.label} href={source.url} target="_blank" rel="noreferrer">{source.label}</a> : <span key={source.label}>{source.label}</span>)}</div> : null}
          </> : null}
        </section>
      </div>
    </> : null}
  </main>;
}
