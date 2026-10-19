import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { SemiconductorLineChart } from "../components/SemiconductorLineChart";
import { SemiconductorSummaryStrip } from "../components/SemiconductorSummaryStrip";
import { DataRefreshStatus } from "../components/DataRefreshStatus";
import { ErrorNotice } from "../components/ErrorNotice";
import { LoadingSpinner } from "../components/LoadingSpinner";
import { RecentFinancialCells } from "../components/RecentFinancials";
import { effectiveHistory, formatPercent, formatWon, parseMarketCapWon, PERIODS, sectorReturn, sectorSeries, stockReturn } from "../dataClient/semiconductorMath";
import type { Period } from "../dataClient/semiconductorMath";
import { stockClassifications } from "../dataClient/semiconductorTypes";
import type { SemiconductorClassification, SemiconductorStock } from "../dataClient/semiconductorTypes";
import { getSemiconductorData } from "../dataClient/staticStockDataClient";
import { usePollingData } from "../dataClient/usePollingData";

type Level = "major" | "middle" | "minor";
type SortDirection = "asc" | "desc";
type SectorSortKey = "count" | Period;
type StockSortKey = "price" | "marketCap" | "change" | "gain" | "revenue" | "operatingIncome";

function compareNullable(a: number | null | undefined, b: number | null | undefined, direction: SortDirection): number {
  if (a === null || a === undefined) return b === null || b === undefined ? 0 : 1;
  if (b === null || b === undefined) return -1;
  return (a - b) * (direction === "asc" ? 1 : -1);
}

function sortableHeader(label: string, active: boolean, direction: SortDirection, onClick: () => void) {
  return <th className="semiNumber" aria-sort={active ? direction === "asc" ? "ascending" : "descending" : "none"}>
    <button type="button" className={`semiSortButton ${active ? "active" : ""}`} onClick={onClick}
      aria-label={`${label} ${active && direction === "desc" ? "오름차순" : "내림차순"} 정렬`}>
      {label}<span aria-hidden="true">{active ? direction === "asc" ? "↑" : "↓" : "↕"}</span>
    </button>
  </th>;
}

function groupLabel(item: SemiconductorClassification, level: Level): string {
  if (level === "major") return item.major;
  if (level === "middle") return `${item.major} / ${item.middle}`;
  return `${item.major} / ${item.middle} / ${item.minor}`;
}

interface SectorGroup {
  name: string;
  classification: SemiconductorClassification;
  stocks: SemiconductorStock[];
}

export function SemiconductorTrendsPage() {
  const { data, error, loading, refreshing, lastCheckedAt, lastSourceAt, refresh } = usePollingData(getSemiconductorData, 300_000);
  const [level, setLevel] = useState<Level>("major");
  const [major, setMajor] = useState("");
  const [period, setPeriod] = useState<Period>(30);
  const [selected, setSelected] = useState("");
  const [sectorSort, setSectorSort] = useState<{ key: SectorSortKey | null; direction: SortDirection }>({ key: null, direction: "asc" });
  const [stockSort, setStockSort] = useState<{ key: StockSortKey; direction: SortDirection }>({ key: "gain", direction: "desc" });
  const stocks = data?.stocks ?? [];
  const categories = data?.categories ?? stocks.flatMap(stockClassifications);
  const majors = [...new Set(categories.map((item) => item.major))];
  const groups = useMemo(() => {
    const map = new Map<string, SectorGroup>();
    for (const stock of stocks) {
      for (const classification of stockClassifications(stock)) {
        if (major && classification.major !== major) continue;
        const name = groupLabel(classification, level);
        if (!map.has(name)) map.set(name, { name, classification, stocks: [] });
        const group = map.get(name)!;
        if (!group.stocks.some((member) => member.ticker === stock.ticker)) group.stocks.push(stock);
      }
    }
    const order = new Map(categories.map((item, index) => [groupLabel(item, level), index]));
    return [...map.values()].sort((a, b) => (order.get(a.name) ?? Infinity) - (order.get(b.name) ?? Infinity));
  }, [stocks, categories, level, major]);
  const active = groups.find((group) => group.name === selected) ?? groups[0];
  const activeStocks = active?.stocks ?? [];
  const chart = useMemo(() => sectorSeries(activeStocks, period), [activeStocks, period]);
  const sortedGroups = useMemo(() => [...groups].sort((a, b) => {
    if (sectorSort.key === null) return 0;
    const aValue = sectorSort.key === "count" ? a.stocks.length : sectorReturn(a.stocks, sectorSort.key).value;
    const bValue = sectorSort.key === "count" ? b.stocks.length : sectorReturn(b.stocks, sectorSort.key).value;
    return compareNullable(aValue, bValue, sectorSort.direction) || a.name.localeCompare(b.name, "ko");
  }), [groups, sectorSort]);
  const ranked = useMemo(() => activeStocks.map((stock) => ({
    stock,
    classification: stockClassifications(stock).find((item) => groupLabel(item, level) === active?.name) ?? stockClassifications(stock)[0],
    price: stock.quote.price ?? effectiveHistory(stock).at(-1)?.close,
    marketCap: parseMarketCapWon(stock.metrics.marketValue),
    change: stock.quote.change_pct,
    gain: stockReturn(stock, period),
    revenue: stock.recent_financials?.revenue,
    operatingIncome: stock.recent_financials?.operating_income,
  })).sort((a, b) => compareNullable(a[stockSort.key], b[stockSort.key], stockSort.direction)
    || a.stock.name.localeCompare(b.stock.name, "ko") || a.stock.code.localeCompare(b.stock.code)), [activeStocks, active, level, period, stockSort]);
  function toggleSectorSort(key: SectorSortKey) {
    setSectorSort((current) => ({ key, direction: current.key === key && current.direction === "desc" ? "asc" : "desc" }));
  }
  function toggleStockSort(key: StockSortKey) {
    setStockSort((current) => ({ key, direction: current.key === key && current.direction === "desc" ? "asc" : "desc" }));
  }

  return <main className="pageShell semiPage semiOverviewPage">
    <header className="semiHero"><div><p className="eyebrow">SECTOR PERFORMANCE</p><h1>반도체 섹터 주가 추이</h1>
      <p>7·30·90·180·360일 수익률을 분류별로 비교하고, 구성 종목의 흐름을 확인합니다.</p></div>
      <Link className="semiHeroLink" to="/semiconductors">종목 목록으로 ↗</Link></header>
    <DataRefreshStatus refreshing={refreshing} lastCheckedAt={lastCheckedAt} lastSourceAt={lastSourceAt} generatedAt={data?.quoted_at} cadence="semiconductor" onRefresh={refresh} />
    {loading && <LoadingSpinner />}{error && <ErrorNotice message={error} />}
    {data && <>
      <SemiconductorSummaryStrip data={data} />
      <section className="semiPanel semiFilterPanel" aria-label="섹터 필터"><div className="semiPanelHeading"><h2>섹터 탐색</h2><p>산업 분류와 연관 테마를 함께 비교합니다. 여러 섹터에 속한 종목은 각 섹터에 한 번씩 포함됩니다.</p></div>
        <div className="semiFilters semiTrendFilters"><label>분류 단계<select value={level} onChange={(event) => { setLevel(event.target.value as Level); setSelected(""); }}>
          <option value="major">대분류</option><option value="middle">중분류</option><option value="minor">소분류</option></select></label>
          <label>대분류<select value={major} onChange={(event) => { setMajor(event.target.value); setSelected(""); }}><option value="">전체</option>{majors.map((name) => <option key={name}>{name}</option>)}</select></label></div>
      </section>
      <section className="semiPanel"><div className="semiPanelHeading"><h2>섹터별 상승률</h2><p>구성 종목의 조정 종가 수익률을 동일 비중으로 평균했습니다.</p></div>
        <div className="semiTableWrap"><table className="semiTable semiTrendTable"><thead><tr><th>대분류</th><th>중분류</th><th>소분류</th>
          {sortableHeader("종목 수", sectorSort.key === "count", sectorSort.direction, () => toggleSectorSort("count"))}
          {PERIODS.map((days) => <th key={days} className="semiNumber" aria-sort={sectorSort.key === days ? sectorSort.direction === "asc" ? "ascending" : "descending" : "none"}>
            <button type="button" className={`semiSortButton ${sectorSort.key === days ? "active" : ""}`} onClick={() => toggleSectorSort(days)}
              aria-label={`${days}일 수익률 ${sectorSort.key === days && sectorSort.direction === "desc" ? "오름차순" : "내림차순"} 정렬`}>
              {days}일<span aria-hidden="true">{sectorSort.key === days ? sectorSort.direction === "asc" ? "↑" : "↓" : "↕"}</span>
            </button>
          </th>)}</tr></thead><tbody>
          {sortedGroups.map(({ name, classification, stocks: members }) => <tr key={name} className={active?.name === name ? "selected" : ""}>
            <td>{level === "major" ? <button type="button" className="semiTextButton" onClick={() => setSelected(name)}>{classification.major}</button> : classification.major}</td>
            <td>{level === "middle" ? <button type="button" className="semiTextButton" onClick={() => setSelected(name)}>{classification.middle}</button> : level === "minor" ? classification.middle : "-"}</td>
            <td>{level === "minor" ? <button type="button" className="semiTextButton" onClick={() => setSelected(name)}>{classification.minor}</button> : "-"}</td>
            <td className="semiNumber">{members.length}개</td>
            {PERIODS.map((days) => { const result = sectorReturn(members, days); return <td key={days} className={`semiNumber ${result.value === null ? "" : result.value > 0 ? "semiUp" : result.value < 0 ? "semiDown" : ""}`} title={`${result.count}/${result.total}개 종목 계산 가능`}>
              {formatPercent(result.value)}<small>{result.count}/{result.total}</small></td>; })}</tr>)}
        </tbody></table></div>
      </section>
      {active && <><section className="semiPanel"><div className="semiPanelHeading semiHeadingSplit"><div><h2>{active.name}</h2><p>{activeStocks.length}개 구성 종목 · 기준값 100 · 동일 비중 평균</p></div>
        <div className="semiPeriodTabs" aria-label="차트 기간">{PERIODS.map((days) => <button key={days} type="button" className={period === days ? "active" : ""} onClick={() => setPeriod(days)}>{days}일</button>)}</div></div>
        <div className="semiTrendHeadline"><strong className={(sectorReturn(activeStocks, period).value ?? 0) >= 0 ? "semiUp" : "semiDown"}>{formatPercent(sectorReturn(activeStocks, period).value)}</strong>
          <span>계산 가능 {sectorReturn(activeStocks, period).count}/{activeStocks.length}개</span></div>
        <SemiconductorLineChart points={chart} title={`${active.name} ${period}일`} unit="지수" />
      </section>
      <section className="semiPanel"><div className="semiPanelHeading semiHeadingSplit"><div><h2>구성 종목 수익률</h2><p>{activeStocks.length}개 종목 · {period}일 조정 종가 기준 · 가장 최근 제공 가격</p></div>
        <div className="semiPeriodTabs" aria-label="구성 종목 수익률 기간">{PERIODS.map((days) => <button key={days} type="button" className={period === days ? "active" : ""} onClick={() => setPeriod(days)}>{days}일</button>)}</div></div>
        <div className="semiTableWrap"><table className="semiTable semiStockPriceTable semiConstituentTable"><thead><tr><th>종목</th><th>대분류</th><th>중분류</th><th>소분류</th><th>시장</th>
          {sortableHeader("가격", stockSort.key === "price", stockSort.direction, () => toggleStockSort("price"))}
          {sortableHeader("시가총액", stockSort.key === "marketCap", stockSort.direction, () => toggleStockSort("marketCap"))}
          <th>기준일</th>
          {sortableHeader("등락률", stockSort.key === "change", stockSort.direction, () => toggleStockSort("change"))}
          {sortableHeader(`${period}일 수익률`, stockSort.key === "gain", stockSort.direction, () => toggleStockSort("gain"))}
          {sortableHeader("최근 1년 매출", stockSort.key === "revenue", stockSort.direction, () => toggleStockSort("revenue"))}
          {sortableHeader("최근 1년 영업이익", stockSort.key === "operatingIncome", stockSort.direction, () => toggleStockSort("operatingIncome"))}<th>실적 기간</th></tr></thead><tbody>
          {ranked.map(({ stock, classification, price, change, gain }) => { const latest = effectiveHistory(stock).at(-1);
            return <tr key={stock.ticker}><td><Link className="semiStockLink" to={`/semiconductors/${encodeURIComponent(stock.ticker)}`}><strong>{stock.name}</strong><span>{stock.code}</span></Link></td>
              <td>{classification.major}</td><td>{classification.middle}</td><td>{classification.minor}</td><td>{stock.market}</td>
              <td className="semiNumber">{formatWon(price)}</td>
              <td className="semiNumber">{stock.metrics.marketValue || "-"}</td>
              <td>{stock.quote.provider_time?.slice(0, 10) ?? latest?.date ?? "-"}</td>
              <td className={`semiNumber ${change === null ? "" : change > 0 ? "semiUp" : change < 0 ? "semiDown" : ""}`}>{formatPercent(change)}</td>
              <td className={`semiNumber ${gain === null ? "" : gain > 0 ? "semiUp" : gain < 0 ? "semiDown" : ""}`}>{formatPercent(gain)}</td>
              <RecentFinancialCells summary={stock.recent_financials} /></tr>; })}
        </tbody></table></div></section></>}
      <p className="semiFootnote">최근 1년 실적(TTM): 최신 발표 분기까지 최근 4개 분기 매출·영업이익 합계, 단위는 억원입니다. 추정치는 제외하며 실적 기간을 종목별로 표시합니다. 연속 4개 분기가 부족하면 최근 결산 연간 실적을 대체 표시합니다.</p>
      <p className="semiFootnote">섹터 수익률은 지수나 ETF 수익률이 아닙니다. 각 종목의 기준일 이전 가장 가까운 거래일 대비 조정 종가 수익률을 동일 비중 평균한 값입니다. 상장 기간 부족 또는 가격 누락 종목은 계산에서 제외하며 각 셀에 포함 수를 표시합니다. 가격 출처: Yahoo Finance 일봉, 누락된 최근 거래일과 현재가는 Naver Finance. 시가총액은 최근 수집값입니다.</p>
    </>}
  </main>;
}
