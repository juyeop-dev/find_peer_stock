import { useCallback, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ErrorNotice } from "../components/ErrorNotice";
import { LoadingSpinner } from "../components/LoadingSpinner";
import { getCalendarHistory, getNewHighIndex, getTurnoverIndex } from "../dataClient/staticStockDataClient";
import { usePollingData } from "../dataClient/usePollingData";
import { addMoney, formatHistoryMoney, historyDays, mergeHistoryStocks, summarizeDays } from "../dataClient/calendarHistory";
import type { HistoryKind, MoneyTotals } from "../dataClient/calendarHistory";
import "../styles/calendarHistory.css";

async function loadIndexes(signal: AbortSignal) {
  const [highs, turnover] = await Promise.all([getNewHighIndex(signal), getTurnoverIndex(signal)]);
  return { highs, turnover };
}
const number = (value: number) => new Intl.NumberFormat("ko-KR").format(value);
const WEEKDAYS = ["일", "월", "화", "수", "목", "금", "토"];

export function CalendarHistoryPage() {
  const [params, setParams] = useSearchParams();
  const { data: indexes, error, loading } = usePollingData(loadIndexes);
  const [search, setSearch] = useState("");
  const [visibleStocks, setVisibleStocks] = useState(50);
  const kind: HistoryKind = params.get("kind") === "turnover" ? "turnover" : "new-highs";
  const yearly = params.get("view") === "year";
  const markets = indexes?.highs.markets ?? [];
  const market = markets.find((item) => item.id === params.get("market"))
    ?? markets.find((item) => item.id === "korea") ?? markets[0];
  const marketId = market?.id ?? "korea";
  const allDays = useMemo(() => indexes ? historyDays(indexes.highs, indexes.turnover, kind, marketId) : [], [indexes, kind, marketId]);
  const years = useMemo(() => [...new Set([
    ...(indexes?.highs.reports ?? []), ...(indexes?.turnover.reports ?? []),
  ].filter((item) => item.market === marketId).map((item) => item.date.slice(0, 4)))].sort().reverse(), [indexes, marketId]);
  const latest = allDays.at(-1)?.date ?? [...(indexes?.highs.reports ?? []), ...(indexes?.turnover.reports ?? [])]
    .filter((item) => item.market === marketId).map((item) => item.date).sort().at(-1) ?? "";
  const year = years.includes(params.get("year") ?? "") ? params.get("year")! : latest.slice(0, 4);
  const requestedMonth = params.get("month") ?? "";
  const monthNumber = /^(0[1-9]|1[0-2])$/.test(requestedMonth) ? requestedMonth
    : (allDays.filter((day) => day.date.startsWith(year)).at(-1)?.date.slice(5, 7) ?? "01");
  const month = `${year}-${monthNumber}`;
  const prefix = yearly ? year : month;
  const days = useMemo(() => allDays.filter((day) => day.date.startsWith(prefix)), [allDays, prefix]);
  const totals = useMemo(() => summarizeDays(days), [days]);
  const hasYear = allDays.some((day) => day.date.startsWith(year));
  const loadHistory = useCallback(async (signal: AbortSignal) => {
    const payload = await getCalendarHistory(kind, marketId, year, signal);
    if (payload.kind !== kind || payload.market !== marketId || payload.year !== year) {
      throw new Error("선택한 기간과 누적 기록이 일치하지 않습니다.");
    }
    return payload;
  }, [kind, marketId, year]);
  const { data: loadedHistory, error: historyError, loading: historyLoading, refresh } = usePollingData(hasYear ? loadHistory : null);
  const history = loadedHistory?.kind === kind && loadedHistory.market === marketId && loadedHistory.year === year ? loadedHistory : null;
  const stocks = useMemo(() => history ? mergeHistoryStocks(history, prefix) : [], [history, prefix]);
  const query = search.trim().toLocaleLowerCase();
  const matchingStocks = stocks.filter((stock) => [stock.name, stock.ticker, stock.category, stock.exchange].join(" ").toLocaleLowerCase().includes(query));
  const index = kind === "new-highs" ? indexes?.highs : indexes?.turnover;
  const closures = new Map((index?.closures ?? []).filter((item) => item.market === marketId).map((item) => [item.date, item.reason || "시장 휴장"]));
  const dayMap = new Map(days.map((day) => [day.date, day]));
  const maxCount = Math.max(1, ...days.map((day) => day.count));
  const months = Array.from({ length: 12 }, (_, i) => {
    const key = `${year}-${String(i + 1).padStart(2, "0")}`;
    return { key, ...summarizeDays(allDays.filter((day) => day.date.startsWith(key))) };
  });
  const firstWeekday = year ? new Date(`${month}-01T00:00:00Z`).getUTCDay() : 0;
  const dayCount = year ? new Date(Date.UTC(Number(year), Number(monthNumber), 0)).getUTCDate() : 0;
  const label = kind === "new-highs" ? "신고가" : "거래대금";
  const periodLabel = yearly ? `${year}년` : `${year}년 ${Number(monthNumber)}월`;
  const detailsUrl = (date: string) => `/${kind}?${new URLSearchParams({ market: marketId, date, ...(kind === "new-highs" ? { exchange: "all" } : {}) })}`;

  function update(values: Record<string, string | null>) {
    const next = new URLSearchParams(params);
    for (const [key, value] of Object.entries(values)) {
      if (value === null) next.delete(key);
      else next.set(key, value);
    }
    setParams(next);
    setVisibleStocks(50);
    setSearch("");
  }
  const rows = yearly ? months
    : days.map((day) => ({ key: day.date, ...summarizeDays([day]) }));
  let cumulativeCount = 0;
  const cumulativeMoney: MoneyTotals = {};

  return <main className="pageShell historyPage">
    <header className="historyHero">
      <div><p className="eyebrow">MARKET ARCHIVE</p><h1>캘린더 누적 기록</h1>
        <p>하루의 기록을 모아, 한 달과 한 해의 시장 흐름을 확인하세요.</p></div>
      <div className="historyHeroLinks"><Link to="/new-highs">신고가 캘린더 ↗</Link><Link to="/turnover">거래대금 캘린더 ↗</Link></div>
    </header>
    {error ? <ErrorNotice message={error} /> : null}
    {!indexes && loading ? <LoadingSpinner /> : null}
    {indexes && market ? <>
      <section className="historyFilters" aria-label="누적 기록 조회 조건">
        <div className="historyFilterTop">
          <div className="historySwitch" role="group" aria-label="기록 종류">
            <button aria-pressed={kind === "new-highs"} onClick={() => update({ kind: "new-highs" })}>신고가</button>
            <button aria-pressed={kind === "turnover"} onClick={() => update({ kind: "turnover" })}>거래대금</button>
          </div>
          <div className="historySwitch" role="group" aria-label="집계 기간">
            <button aria-pressed={!yearly} onClick={() => update({ view: "month" })}>월별</button>
            <button aria-pressed={yearly} onClick={() => update({ view: "year" })}>연도별</button>
          </div>
        </div>
        <div className="historyFilterFields">
          <label>시장<select value={marketId} onChange={(event) => update({ market: event.target.value, year: null, month: null })}>
            {markets.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
          </select></label>
          <label>연도<select value={year} disabled={!years.length} onChange={(event) => update({ year: event.target.value, month: null })}>
            {years.length ? years.map((item) => <option key={item} value={item}>{item}년</option>) : <option value="">기록 없음</option>}
          </select></label>
          {!yearly ? <label>월<select value={monthNumber} onChange={(event) => update({ month: event.target.value })}>
            {months.map((item, i) => <option key={item.key} value={item.key.slice(5)}>{i + 1}월{item.days ? ` · ${item.days}일 기록` : " · 기록 없음"}</option>)}
          </select></label> : null}
          <button className="historyLatest" onClick={() => update({ year: null, month: null })}>최신 기록</button>
        </div>
      </section>
      <div className="historyPeriodHeading"><div><span className="eyebrow">{market.label} · {yearly ? "연간" : "월간"} 아카이브</span>
        <h2>{year ? periodLabel : "저장된 기록 없음"} <span>{label}</span></h2></div>
        {days.length ? <p>{days[0].date} ~ {days.at(-1)!.date}<br />저장된 거래일 기준</p> : null}
      </div>
      <section className="historySummary" aria-label="기간 누적 요약">
        <article><span>기록된 거래일</span><strong>{number(totals.days)}<small>일</small></strong><p>선택한 기간에 저장된 리포트</p></article>
        <article className="historySummaryAccent"><span>{kind === "new-highs" ? "신고가 누적 기록" : "TOP 30 누적 거래대금"}</span>
          <strong className={kind === "turnover" ? "historyMoney" : ""}>{kind === "new-highs" ? <>{number(totals.count)}<small>건</small></>
            : formatHistoryMoney(totals.money)}</strong><p>{kind === "new-highs" ? "동일 종목의 다른 날짜 기록 포함" : "각 거래일 상위 종목의 거래대금 합계"}</p></article>
        <article><span>{kind === "new-highs" ? "52주 / 역대 신고가" : "TOP 30 누적 등장"}</span>
          <strong>{kind === "new-highs" ? `${number(totals.high52)} / ${number(totals.highAll)}` : number(totals.count)}<small>건</small></strong>
          <p>{kind === "new-highs" ? "역대 신고가는 52주 집계에서 제외" : "날짜마다 기록된 종목 수의 합계"}</p></article>
        <article><span>기간 내 고유 종목</span><strong>{history ? number(stocks.length) : hasYear ? "—" : "0"}<small>종목</small></strong><p>같은 티커는 한 번만 집계</p></article>
      </section>
      <section className="historyPanel">
        <div className="historySectionHeading"><div><h3>{yearly ? "월별 기록 한눈에 보기" : "일별 기록 캘린더"}</h3>
          <p>{yearly ? "월을 선택하면 해당 월의 누적 기록으로 이동합니다." : "기록이 있는 날짜를 선택하면 그날의 상세 리포트로 이동합니다."}</p></div>
          <span className="historyLegend"><i />기록 있음 <i className="isEmpty" />미등록</span>
        </div>
        {yearly ? <div className="historyMonthGrid">{months.map((item, i) => <button key={item.key}
          className={item.days ? "hasRecords" : ""} onClick={() => update({ view: "month", month: item.key.slice(5), year })}>
          <span>{i + 1}월 <small>{item.days ? `${item.days}일 기록` : "기록 없음"}</small></span>
          <strong>{item.days ? kind === "new-highs" ? `${number(item.count)}건` : formatHistoryMoney(item.money) : "—"}</strong>
          {item.days ? <div className="historyMonthBar"><i style={{ width: `${Math.max(2, item.count / Math.max(1, ...months.map((value) => value.count)) * 100)}%` }} /></div> : null}
        </button>)}</div> : <div className="historyCalendar" aria-label={`${periodLabel} ${label} 기록`}>
          {WEEKDAYS.map((day) => <span className="historyWeekday" key={day}>{day}</span>)}
          {Array.from({ length: firstWeekday }, (_, i) => <div className="historyBlank" key={`blank-${i}`} />)}
          {Array.from({ length: dayCount }, (_, i) => {
            const date = `${month}-${String(i + 1).padStart(2, "0")}`;
            const day = dayMap.get(date);
            const weekend = (firstWeekday + i) % 7 === 0 || (firstWeekday + i) % 7 === 6;
            const closed = !day && (weekend || closures.has(date));
            const content = <><span>{i + 1}</span><strong>{day ? `${number(day.count)}${kind === "new-highs" ? "건" : "종목"}` : closed ? "휴장" : "미등록"}</strong>
              {day && kind === "turnover" ? <small>{formatHistoryMoney(day.money)}</small> : day ? <small>52주 {day.high52} · 역대 {day.highAll}</small> : null}</>;
            return day ? <Link key={date} to={detailsUrl(date)} className="historyDay hasRecords"
              style={{ backgroundColor: `rgba(33, 117, 108, ${0.04 + day.count / maxCount * 0.15})` }}
              aria-label={`${date} ${label} ${day.count}건 상세 보기`}>{content}</Link>
              : <div key={date} className={`historyDay ${closed ? "isClosed" : ""}`} title={closures.get(date)}>{content}</div>;
          })}
        </div>}
      </section>
      {!days.length ? <div className="historyEmpty"><strong>선택한 기간에 저장된 {label} 기록이 없습니다.</strong><p>다른 기간을 선택하거나 최신 기록을 확인해 주세요.</p></div> : null}
      <section className="historyPanel" aria-label="누적 추이">
        <div className="historySectionHeading"><div><h3>{yearly ? "월별" : "일별"} 누적 추이</h3><p>선택한 기간의 첫 기록부터 차례로 합산합니다. 미등록 기간은 합계에 포함하지 않습니다.</p></div></div>
        <div className="historyTableScroll"><table className="historyTable historyTotalsTable"><thead><tr>
          <th scope="col">{yearly ? "월" : "거래일"}</th><th scope="col">기록일</th><th scope="col">{kind === "new-highs" ? "신고가 건수" : "등장 건수"}</th>
          {kind === "new-highs" ? <><th scope="col">52주 / 역대</th><th scope="col">누적 신고가</th></>
            : <><th scope="col">TOP 30 거래대금</th><th scope="col">누적 거래대금</th></>}
        </tr></thead><tbody>{rows.map((row) => {
          cumulativeCount += row.count;
          addMoney(cumulativeMoney, row.money);
          return <tr key={row.key}><th scope="row">{yearly ? <button onClick={() => update({ view: "month", year, month: row.key.slice(5) })}>{Number(row.key.slice(5))}월 ↗</button>
            : <Link to={detailsUrl(row.key)}>{row.key} ↗</Link>}</th><td>{row.days ? `${row.days}일` : "미등록"}</td><td>{row.days ? number(row.count) : "—"}</td>
            {kind === "new-highs" ? <><td>{row.days ? `${number(row.high52)} / ${number(row.highAll)}` : "—"}</td><td className="historyCumulative">{number(cumulativeCount)}건</td></>
              : <><td>{formatHistoryMoney(row.money)}</td><td className="historyCumulative">{formatHistoryMoney(cumulativeMoney)}</td></>}
          </tr>;
        })}</tbody></table></div>
      </section>
      <section className="historyPanel" aria-busy={historyLoading}>
        <div className="historySectionHeading"><div><h3>종목별 누적 기록 <span>{history ? `${number(stocks.length)}종목` : ""}</span></h3>
          <p>{kind === "new-highs" ? "신고가를 기록한 날짜가 많은 순서입니다." : "거래대금 상위 30위에 등장한 날짜가 많은 순서입니다. 거래대금은 등장일에 한해 합산합니다."}</p></div>
          <input type="search" aria-label="누적 종목 검색" placeholder="종목명 · 티커 · 업종 검색" value={search} onChange={(event) => { setSearch(event.target.value); setVisibleStocks(50); }} />
        </div>
        {historyLoading ? <LoadingSpinner /> : null}
        {historyError ? <><ErrorNotice message={historyError} /><button className="historyRetry" onClick={refresh}>다시 불러오기</button></> : null}
        {history ? <>
          <div className="historyTableScroll"><table className="historyTable historyStocksTable"><thead><tr>
            <th scope="col">순번</th><th scope="col">종목</th><th scope="col">업종</th><th scope="col">등장일</th>
            {kind === "new-highs" ? <th scope="col">52주 / 역대</th> : <th scope="col">누적 거래대금</th>}
            <th scope="col">최초 기록</th><th scope="col">최근 기록</th>
          </tr></thead><tbody>{matchingStocks.slice(0, visibleStocks).map((stock, i) => <tr key={stock.ticker}>
            <td>{i + 1}</td><th scope="row"><Link to={detailsUrl(stock.dates.at(-1)!)}><strong>{stock.name}</strong><small>{stock.ticker} · {stock.exchange}</small></Link></th>
            <td className="historyCategory">{stock.category}</td><td><strong>{stock.dates.length}일</strong></td>
            <td>{kind === "new-highs" ? `${stock.high_52_week} / ${stock.high_all_time}` : formatHistoryMoney(stock.turnover_by_currency)}</td>
            <td><Link to={detailsUrl(stock.dates[0])}>{stock.dates[0]} ↗</Link></td><td><Link to={detailsUrl(stock.dates.at(-1)!)}>{stock.dates.at(-1)} ↗</Link></td>
          </tr>)}</tbody></table></div>
          {!matchingStocks.length ? <div className="historyEmpty"><strong>{search ? "검색 결과가 없습니다." : "이 기간에 기록된 종목이 없습니다."}</strong></div> : null}
          {matchingStocks.length > visibleStocks ? <button className="historyShowMore" onClick={() => setVisibleStocks((value) => value + 50)}>50종목 더 보기 · {number(visibleStocks)} / {number(matchingStocks.length)}</button> : null}
        </> : null}
      </section>
      <footer className="historyFootnote"><strong>집계 기준</strong><p>누적 건수는 종목과 거래일의 조합을 셉니다. 고유 종목 수는 선택 기간의 티커 중복을 제거합니다.
        신고가는 52주·역대 유형을 중복 합산하지 않습니다. 거래대금은 저장된 상위 30종목의 합계이며 시장 전체 거래대금과 다릅니다.
        통화별 금액은 환산하지 않고 각각 표시합니다. 미수집 날짜는 0건으로 처리하지 않습니다.</p></footer>
    </> : null}
  </main>;
}
