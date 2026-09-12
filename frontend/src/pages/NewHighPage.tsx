import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ErrorNotice } from "../components/ErrorNotice";
import { LoadingSpinner } from "../components/LoadingSpinner";
import { NewHighCalendar } from "../components/NewHighCalendar";
import { DataRefreshStatus } from "../components/DataRefreshStatus";
import { getNewHighIndex, getNewHighReport, getSiteIndex } from "../dataClient/staticStockDataClient";
import { usePollingData } from "../dataClient/usePollingData";
import type { HighType, NewHighCounts, NewHighEntry } from "../dataClient/newHighTypes";

const EMPTY_COUNTS: NewHighCounts = { total: 0, high_52_week: 0, high_all_time: 0 };
const HIGH_TYPES: { id: HighType; label: string; description: string }[] = [
  { id: "all_time", label: "역대 신고가", description: "상장 이후 최고가를 새로 기록한 종목" },
  { id: "52_week", label: "52주 신고가", description: "최근 52주 최고가를 새로 기록한 종목" }
];

function validDate(value: string | null): value is string {
  if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value) || Number(value.slice(0, 4)) < 1) return false;
  const parsed = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
}

function dateInTimezone(timezone: string): string {
  const parts = new Intl.DateTimeFormat("en", {
    timeZone: timezone, year: "numeric", month: "2-digit", day: "2-digit"
  }).formatToParts(new Date());
  return ["year", "month", "day"].map((type) => parts.find((part) => part.type === type)?.value).join("-");
}

function readableDate(value: string): string {
  return new Intl.DateTimeFormat("ko-KR", {
    timeZone: "UTC", year: "numeric", month: "long", day: "numeric", weekday: "long"
  }).format(new Date(`${value}T00:00:00Z`));
}

export function NewHighPage() {
  const [params, setParams] = useSearchParams();
  const { data: index, error: indexError, loading: indexLoading,
    refreshing: indexRefreshing, lastCheckedAt, refresh: refreshIndex } = usePollingData(getNewHighIndex);
  const { data: peerIndex, refresh: refreshPeers } = usePollingData(getSiteIndex);
  const [month, setMonth] = useState("");
  const [search, setSearch] = useState("");
  const [highType, setHighType] = useState<HighType | "all">("all");
  const peerTickers = useMemo(() => new Set(peerIndex?.stocks.map((stock) => stock.ticker) ?? []), [peerIndex]);

  const market = index?.markets.find((item) => item.id === params.get("market"))
    ?? index?.markets.find((item) => item.id === "korea") ?? index?.markets[0];
  const marketId = market?.id ?? "korea";
  const today = dateInTimezone(market?.timezone ?? "Asia/Seoul");
  const marketReports = useMemo(() => (index?.reports ?? [])
    .filter((item) => item.market === marketId)
    .sort((a, b) => b.date.localeCompare(a.date)), [index, marketId]);
  const requestedDate = params.get("date");
  const selectedDate = validDate(requestedDate) ? requestedDate : marketReports[0]?.date ?? today;
  const requestedExchange = params.get("exchange");
  const exchange = requestedExchange === "all" || market?.exchanges.some((item) => item.id === requestedExchange)
    ? requestedExchange! : market?.default_exchange ?? "all";
  const exchangeLabel = exchange === "all" ? "전체 거래소"
    : market?.exchanges.find((item) => item.id === exchange)?.label ?? exchange;
  const indexedReport = marketReports.find((item) => item.date === selectedDate);
  const hasReport = Boolean(indexedReport);
  const loadReport = useCallback(async (signal: AbortSignal) => {
    const payload = await getNewHighReport(marketId, selectedDate, signal);
    if (payload.date !== selectedDate || payload.market !== marketId) {
      throw new Error("선택한 날짜와 기록이 일치하지 않습니다. 새로고침해 주세요.");
    }
    return payload;
  }, [marketId, selectedDate]);
  const { data: reportData, error: reportError, loading: reportLoading,
    refreshing: reportRefreshing, refresh: refreshReport } = usePollingData(hasReport ? loadReport : null);
  const report = hasReport && reportData?.date === selectedDate && reportData.market === marketId ? reportData : null;

  useEffect(() => { setMonth(selectedDate.slice(0, 7)); }, [selectedDate, marketId]);

  function refresh() {
    refreshIndex();
    refreshReport();
    refreshPeers();
  }

  const days = useMemo(() => Object.fromEntries(marketReports.map((item) => [
    item.date, exchange === "all" ? item.counts : item.exchanges[exchange] ?? EMPTY_COUNTS
  ])), [marketReports, exchange]);
  const entries = useMemo(() => (report?.entries ?? [])
    .filter((entry) => exchange === "all" || entry.exchange === exchange), [report, exchange]);
  const counts = report ? {
    total: entries.length,
    high_52_week: entries.filter((entry) => entry.high_type === "52_week").length,
    high_all_time: entries.filter((entry) => entry.high_type === "all_time").length
  } : undefined;
  const query = search.trim().toLocaleLowerCase();
  const filteredEntries = entries.filter((entry) => (highType === "all" || entry.high_type === highType)
    && [entry.name, entry.ticker, entry.category, entry.reason, entry.description,
      report?.category_reasons?.[entry.category]].filter(Boolean).join(" ").toLocaleLowerCase().includes(query));

  function selectDate(date: string) {
    setParams({ market: marketId, exchange, date });
    setMonth(date.slice(0, 7));
  }

  function selectMarket(id: string) {
    const nextMarket = index?.markets.find((item) => item.id === id);
    if (!nextMarket) return;
    const date = index?.reports.filter((item) => item.market === id)
      .map((item) => item.date).sort().at(-1) ?? dateInTimezone(nextMarket.timezone);
    setParams({ market: id, exchange: nextMarket.default_exchange, date });
    setSearch("");
    setHighType("all");
  }

  return (
    <main className="pageShell newHighPage">
      <header className="newHighHeader">
        <div>
          <p className="eyebrow">DAILY MARKET ARCHIVE</p>
          <h1>신고가 캘린더</h1>
          <p className="newHighLead">새로운 고점을 만든 종목, 그 뒤의 이야기를 날짜별로 살펴보세요.</p>
        </div>
      </header>

      <DataRefreshStatus refreshing={indexRefreshing || reportRefreshing}
        lastCheckedAt={lastCheckedAt} onRefresh={refresh} />

      {indexError ? <ErrorNotice message={indexError} /> : null}
      {!index && indexLoading ? <LoadingSpinner /> : null}
      {index && market ? <>
        <div className="newHighMarkets" role="group" aria-label="국가별 시장">
          {index.markets.map((item) => {
            const recorded = index.reports.some((record) => record.market === item.id);
            return <button key={item.id} aria-pressed={marketId === item.id}
              onClick={() => selectMarket(item.id)}>
              {item.label}<span>{recorded ? "기록 있음" : "기록 대기"}</span>
            </button>;
          })}
        </div>

        <div className="newHighLayout">
          <aside className="newHighSidebar" aria-label="신고가 날짜 선택">
            <div className="newHighScope">
              <span className="eyebrow">조회 시장</span>
              <strong>{market.label}</strong>
              <div className="newHighExchanges" role="group" aria-label="거래소 선택">
                {[{ id: "all", label: "전체" }, ...market.exchanges].map((item) => (
                  <button key={item.id} aria-pressed={exchange === item.id}
                    onClick={() => setParams({ market: marketId, date: selectedDate, exchange: item.id })}>
                    {item.label}
                  </button>
                ))}
              </div>
            </div>
            <NewHighCalendar month={month || selectedDate.slice(0, 7)} selectedDate={selectedDate}
              today={today} days={days} onMonthChange={setMonth} onSelectDate={selectDate} />
            <div className="newHighArchiveMeta">
              <label>월 바로 이동
                <input type="month" aria-label="조회할 달" value={month || selectedDate.slice(0, 7)}
                  min="0001-01" max="9999-12"
                  onChange={(event) => {
                    if (validDate(`${event.target.value}-01`)) setMonth(event.target.value);
                  }} />
              </label>
              <p><strong>{marketReports.length}일</strong>의 기록이 쌓였어요.</p>
              {marketReports[0] ? <button className="newHighTextButton"
                onClick={() => selectDate(marketReports[0].date)}>최근 기록 · {marketReports[0].date} →</button>
                : <p>첫 기록이 등록되면 달력에 표시됩니다.</p>}
              <p className="newHighTimezone">날짜는 각 시장의 현지 거래일 기준입니다.</p>
            </div>
          </aside>

          <section className="newHighReport" aria-label="선택한 날짜의 신고가" aria-busy={reportLoading}>
            <div className="newHighReportHeading">
              <div>
                <p className="eyebrow">{market.label} · {exchangeLabel}</p>
                <h2>{readableDate(selectedDate)}</h2>
              </div>
              <span className={`newHighRecordStatus${hasReport ? " isRecorded" : ""}`}>
                {hasReport ? "기록 등록됨" : "미등록"}
              </span>
            </div>

            <div className="newHighStats">
              <div><span>전체 신고가</span><strong>{counts?.total ?? "—"}<small>종목</small></strong></div>
              <div className="allTimeStat"><span><i />역대 신고가</span><strong>{counts?.high_all_time ?? "—"}<small>종목</small></strong></div>
              <div className="weekStat"><span><i />52주 신고가</span><strong>{counts?.high_52_week ?? "—"}<small>종목</small></strong></div>
            </div>
            <p className="newHighCountNote">역대 신고가는 52주 신고가에 중복 집계하지 않습니다.</p>

            {reportLoading ? <LoadingSpinner /> : null}
            {reportError ? <ErrorNotice message={reportError} /> : null}
            {!hasReport ? <div className="newHighEmpty" role="status">
              <span className="newHighEmptyIcon" aria-hidden="true">▦</span>
              <h3>{marketReports.length === 0 ? "아직 등록된 신고가 기록이 없습니다" : "이 날짜의 기록이 아직 없습니다"}</h3>
              <p>{marketReports.length === 0
                ? `${market.label} 시장의 첫 기록을 기다리고 있어요. 매일의 기록이 등록되면 이곳에 종목과 사유가 쌓입니다.`
                : "달력에 표시된 날짜를 선택하면 해당 거래일의 신고가 종목과 사유를 확인할 수 있습니다."}</p>
              <span>미등록 날짜는 신고가 0종목을 뜻하지 않습니다.</span>
            </div> : null}

            {report ? <>
              {report.summary ? <div className="newHighDailyNote"><span>오늘의 시장 메모</span><p>{report.summary}</p></div> : null}
              <div className="newHighFilters">
                <div className="newHighTypeFilters" role="group" aria-label="신고가 유형">
                  <button aria-pressed={highType === "all"} onClick={() => setHighType("all")}>전체</button>
                  {HIGH_TYPES.map((type) => <button key={type.id} aria-pressed={highType === type.id}
                    onClick={() => setHighType(type.id)}>{type.label}</button>)}
                </div>
                <input type="search" value={search} placeholder="종목명, 티커, 테마 검색"
                  aria-label="종목명, 티커, 테마, 사유 검색" onChange={(event) => setSearch(event.target.value)} />
              </div>

              {entries.length === 0 ? <div className="newHighEmpty" role="status">
                <h3>등록된 기록에 {exchangeLabel} 신고가 종목이 없습니다</h3>
                <p>이 날짜의 기록은 등록되어 있으며, 선택한 거래소에 해당하는 종목은 0개입니다.</p>
              </div> : filteredEntries.length === 0 ? <div className="newHighEmpty" role="status">
                <h3>조건에 맞는 종목이 없습니다</h3><p>검색어나 신고가 유형을 바꿔보세요.</p>
                <button className="newHighTextButton" onClick={() => { setSearch(""); setHighType("all"); }}>필터 초기화</button>
              </div> : <div className="newHighResults" aria-live="polite">
                {HIGH_TYPES.filter((type) => highType === "all" || type.id === highType).map((type) => {
                  const typedEntries = filteredEntries.filter((entry) => entry.high_type === type.id);
                  if (!typedEntries.length) return null;
                  const groups = new Map<string, NewHighEntry[]>();
                  typedEntries.forEach((entry) => groups.set(entry.category, [...(groups.get(entry.category) ?? []), entry]));
                  return <section className={`newHighTypeSection ${type.id}`} key={type.id}>
                    <header><div><h3><i />{type.label}<span>{typedEntries.length}</span></h3><p>{type.description}</p></div></header>
                    {[...groups].map(([category, stocks]) => <article className="newHighTheme" key={category}>
                      <header><h4>{category}<span>{stocks.length}종목</span></h4>
                        {report.category_reasons?.[category] ? <p>{report.category_reasons[category]}</p> : null}</header>
                      <ul>{stocks.map((entry) => <li key={entry.ticker}>
                        <div className="newHighStockTop"><div><strong>{entry.name}</strong>
                          <span className="newHighTicker">{entry.ticker}</span><span className="newHighExchange">{entry.exchange}</span></div>
                          <span className={`newHighChange ${entry.change_pct == null || entry.change_pct === 0 ? "flat" : entry.change_pct > 0 ? "up" : "down"}`}
                            aria-label={entry.change_pct == null ? "등락률 미등록" : `당일 등락률 ${entry.change_pct}%`}>
                            {entry.change_pct == null ? "등락률 미등록" : `${entry.change_pct > 0 ? "+" : ""}${entry.change_pct.toFixed(2)}%`}
                          </span>
                        </div>
                        {entry.description ? <p className="newHighDescription">{entry.description}</p> : null}
                        {entry.reason !== report.category_reasons?.[category] ? <p className="newHighReason"><span>신고가 사유</span>{entry.reason}</p> : null}
                        {peerTickers.has(entry.ticker) ? <Link className="newHighPeerLink" to={`/stocks/${encodeURIComponent(entry.ticker)}`}>Peer 비교 보기 →</Link> : null}
                      </li>)}</ul>
                    </article>)}
                  </section>;
                })}
              </div>}
              {report.sources?.length ? <footer className="newHighSources"><strong>자료 출처</strong>
                {report.sources.map((source, i) => source.url && /^https?:\/\//i.test(source.url)
                  ? <a key={i} href={source.url} target="_blank" rel="noopener noreferrer">{source.label} ↗</a>
                  : <span key={i}>{source.label}</span>)}
              </footer> : null}
            </> : null}
          </section>
        </div>
      </> : null}
    </main>
  );
}
