import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { DataRefreshStatus } from "../components/DataRefreshStatus";
import { ErrorNotice } from "../components/ErrorNotice";
import { LoadingSpinner } from "../components/LoadingSpinner";
import { RecentFinancialCells } from "../components/RecentFinancials";
import { SemiconductorSummaryStrip } from "../components/SemiconductorSummaryStrip";
import { effectiveHistory, formatPercent, formatWon, parseMarketCapWon, PERIODS, priceOnDate, stockReturn } from "../dataClient/semiconductorMath";
import type { Period } from "../dataClient/semiconductorMath";
import { stockClassifications } from "../dataClient/semiconductorTypes";
import type { SemiconductorClassification, SemiconductorStock } from "../dataClient/semiconductorTypes";
import { getSemiconductorData } from "../dataClient/staticStockDataClient";
import { usePollingData } from "../dataClient/usePollingData";

function dayChange(stock: SemiconductorStock, date: string): number | null {
  const history = effectiveHistory(stock);
  const index = history.findIndex((point) => point.date === date);
  if (index <= 0 || history[index - 1].close <= 0) return null;
  return (history[index].close / history[index - 1].close - 1) * 100;
}

type SortKey = "name" | "change" | "marketCap" | "gain" | "revenue" | "operatingIncome";
type SortDirection = "asc" | "desc";

function compareNullable(a: number | null | undefined, b: number | null | undefined, direction: SortDirection): number {
  if (a === null || a === undefined) return b === null || b === undefined ? 0 : 1;
  if (b === null || b === undefined) return -1;
  return (a - b) * (direction === "asc" ? 1 : -1);
}

function matchesClassification(item: SemiconductorClassification, major: string, middle: string, minor: string): boolean {
  return (!major || item.major === major) && (!middle || item.middle === middle) && (!minor || item.minor === minor);
}

export function SemiconductorPage() {
  const { data, error, loading, refreshing, lastCheckedAt, lastSourceAt, refresh } = usePollingData(getSemiconductorData, 300_000);
  const [major, setMajor] = useState("");
  const [middle, setMiddle] = useState("");
  const [minor, setMinor] = useState("");
  const [market, setMarket] = useState("");
  const [query, setQuery] = useState("");
  const [date, setDate] = useState("latest");
  const [period, setPeriod] = useState<Period>(30);
  const [sortKey, setSortKey] = useState<SortKey>("name");
  const [sortDirection, setSortDirection] = useState<SortDirection>("asc");
  const stocks = data?.stocks ?? [];
  const categories = data?.categories ?? stocks.flatMap(stockClassifications);
  const majors = [...new Set(categories.map((item) => item.major))];
  const middles = [...new Set(categories.filter((item) => !major || item.major === major).map((item) => item.middle))];
  const minors = [...new Set(categories.filter((item) => (!major || item.major === major) && (!middle || item.middle === middle)).map((item) => item.minor))];
  const dates = useMemo(() => [...new Set(stocks.flatMap((stock) => effectiveHistory(stock).map((point) => point.date)))].sort().reverse(), [stocks]);
  const visible = useMemo(() => stocks.filter((stock) =>
    stockClassifications(stock).some((item) => matchesClassification(item, major, middle, minor)) &&
    (!market || stock.market === market) &&
    (!query || `${stock.name} ${stock.code} ${stockClassifications(stock).map((item) => item.minor).join(" ")}`.toLowerCase().includes(query.toLowerCase()))
  ), [stocks, major, middle, minor, market, query]);
  const rows = useMemo(() => visible.map((stock) => {
    const point = date === "latest" ? effectiveHistory(stock).at(-1) : priceOnDate(stock, date);
    return {
      stock,
      classification: stockClassifications(stock).find((item) => matchesClassification(item, major, middle, minor))!,
      price: date === "latest" ? stock.quote.price ?? point?.close : point?.close,
      asOf: date === "latest" ? stock.quote.provider_time?.slice(0, 10) ?? point?.date ?? "-" : point?.date ?? "-",
      change: date === "latest" ? stock.quote.change_pct : dayChange(stock, date),
      gain: date !== "latest" && !point ? null : stockReturn(stock, period, date === "latest" ? undefined : date),
      marketCap: parseMarketCapWon(stock.metrics.marketValue),
      revenue: stock.recent_financials?.revenue,
      operatingIncome: stock.recent_financials?.operating_income,
    };
  }).sort((a, b) => {
    const result = sortKey === "name" ? a.stock.name.localeCompare(b.stock.name, "ko") * (sortDirection === "asc" ? 1 : -1)
      : compareNullable(a[sortKey], b[sortKey], sortDirection);
    return result || a.stock.name.localeCompare(b.stock.name, "ko") || a.stock.code.localeCompare(b.stock.code);
  }), [visible, date, period, major, middle, minor, sortKey, sortDirection]);
  function toggleSort(key: SortKey) {
    if (sortKey === key) setSortDirection((current) => current === "asc" ? "desc" : "asc");
    else { setSortKey(key); setSortDirection("desc"); }
  }
  function sortHeader(key: SortKey, label: string) {
    const active = sortKey === key;
    return <th className="semiNumber" aria-sort={active ? sortDirection === "asc" ? "ascending" : "descending" : "none"}>
      <button type="button" className={`semiSortButton ${active ? "active" : ""}`} onClick={() => toggleSort(key)}
        aria-label={`${label} ${active && sortDirection === "desc" ? "오름차순" : "내림차순"} 정렬`}>
        {label}<span aria-hidden="true">{active ? sortDirection === "asc" ? "↑" : "↓" : "↕"}</span>
      </button>
    </th>;
  }

  return <main className="pageShell semiPage semiOverviewPage">
    <header className="semiHero">
      <div><p className="eyebrow">KOREA SEMICONDUCTOR MAP</p><h1>국내 반도체 종목</h1>
        <p>대분류 → 중분류 → 소분류로 탐색하고, 선택한 날짜의 가격과 기간 수익률을 비교합니다.</p></div>
      <Link className="semiHeroLink" to="/semiconductors/trends">섹터 주가 추이 보기 ↗</Link>
    </header>
    <DataRefreshStatus refreshing={refreshing} lastCheckedAt={lastCheckedAt} lastSourceAt={lastSourceAt} generatedAt={data?.quoted_at} cadence="semiconductor" onRefresh={refresh} />
    {loading && <LoadingSpinner />}{error && <ErrorNotice message={error} />}
    {data && <>
      <SemiconductorSummaryStrip data={data} />
      <section className="semiPanel semiFilterPanel" aria-label="종목 필터">
        <div className="semiPanelHeading"><h2>섹터 탐색</h2><p>이미지의 산업 구조에 기업 사업 자료로 확인한 종목과 연관 사업을 추가했습니다. 한 종목이 여러 분류에 포함될 수 있습니다.</p></div>
        <div className="semiFilters">
          <label>대분류<select value={major} onChange={(event) => { setMajor(event.target.value); setMiddle(""); setMinor(""); }}>
            <option value="">전체</option>{majors.map((item) => <option key={item}>{item}</option>)}
          </select></label>
          <label>중분류<select value={middle} onChange={(event) => { setMiddle(event.target.value); setMinor(""); }}>
            <option value="">전체</option>{middles.map((item) => <option key={item}>{item}</option>)}
          </select></label>
          <label>소분류<select value={minor} onChange={(event) => setMinor(event.target.value)}>
            <option value="">전체</option>{minors.map((item) => <option key={item}>{item}</option>)}
          </select></label>
          <label>시장<select value={market} onChange={(event) => setMarket(event.target.value)}>
            <option value="">코스피 + 코스닥</option><option value="KOSPI">코스피</option><option value="KOSDAQ">코스닥</option>
          </select></label>
          <label>날짜<select value={date} onChange={(event) => setDate(event.target.value)}>
            <option value="latest">현재가</option>{dates.map((item) => <option key={item} value={item}>{item}</option>)}
          </select></label>
          <label className="semiSearch">종목 검색<input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="종목명 또는 코드" /></label>
        </div>
      </section>
      <section className="semiPanel">
        <div className="semiPanelHeading semiHeadingSplit"><div><h2>종목별 가격</h2><p>{visible.length}개 종목 · {date === "latest" ? "가장 최근 제공 가격" : `${date} 일별 종가`}</p></div>
          <div className="semiPeriodTabs" aria-label="수익률 기간">{PERIODS.map((days) => <button key={days} type="button" className={period === days ? "active" : ""} onClick={() => setPeriod(days)}>{days}일</button>)}</div>
        </div>
        <div className="semiTableWrap"><table className="semiTable semiStockPriceTable"><thead><tr><th>종목</th><th>대분류</th><th>중분류</th><th>소분류</th><th>시장</th><th className="semiNumber">가격</th>{sortHeader("marketCap", "시가총액")}<th>기준일</th>{sortHeader("change", "등락률")}{sortHeader("gain", `${period}일 수익률`)}{sortHeader("revenue", "최근 1년 매출")}{sortHeader("operatingIncome", "최근 1년 영업이익")}<th>실적 기간</th></tr></thead><tbody>
          {rows.map(({ stock, classification, price, asOf, change, gain }) => {
            return <tr key={stock.ticker}><td><Link className="semiStockLink" to={`/semiconductors/${encodeURIComponent(stock.ticker)}`}><strong>{stock.name}</strong><span>{stock.code}</span></Link></td>
              <td>{classification.major}</td><td>{classification.middle}</td><td>{classification.minor}</td><td>{stock.market}</td>
              <td className="semiNumber">{formatWon(price)}</td><td className="semiNumber">{stock.metrics.marketValue || "-"}</td><td>{asOf}</td>
              <td className={`semiNumber ${change === null || change === undefined ? "" : change > 0 ? "semiUp" : change < 0 ? "semiDown" : ""}`}>{formatPercent(change)}</td>
              <td className={`semiNumber ${gain === null ? "" : gain > 0 ? "semiUp" : gain < 0 ? "semiDown" : ""}`}>{formatPercent(gain)}</td>
              <RecentFinancialCells summary={stock.recent_financials} /></tr>;
          })}
        </tbody></table>{visible.length === 0 && <p className="semiEmpty">조건에 맞는 종목이 없습니다.</p>}</div>
      </section>
      <p className="semiFootnote">최근 1년 실적(TTM): 최신 발표 분기까지 최근 4개 분기 매출·영업이익 합계, 단위는 억원입니다. 추정치는 제외하며 실적 기간을 종목별로 표시합니다. 연속 4개 분기가 부족하면 최근 결산 연간 실적을 대체 표시합니다. 실적은 선택한 가격 날짜와 관계없이 최신 발표 자료입니다.</p>
      <p className="semiFootnote">가격: Naver Finance 현재가 / Yahoo Finance 일봉. 누락된 최근 거래일은 Naver Finance 일봉으로 보완합니다. 시가총액은 선택 날짜와 관계없이 최근 수집값입니다. 수익률은 배당·분할 조정 종가 기준이며, 기준 날짜 이전 가장 가까운 거래일과 비교합니다. 현재가는 실시간 체결가가 아니며 제공처 기준 시각을 확인하세요.</p>
    </>}
  </main>;
}
