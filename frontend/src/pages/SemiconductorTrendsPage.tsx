import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { SemiconductorLineChart } from "../components/SemiconductorLineChart";
import { DataRefreshStatus } from "../components/DataRefreshStatus";
import { ErrorNotice } from "../components/ErrorNotice";
import { LoadingSpinner } from "../components/LoadingSpinner";
import { effectiveHistory, formatPercent, formatWon, PERIODS, sectorReturn, sectorSeries, stockReturn } from "../dataClient/semiconductorMath";
import type { Period } from "../dataClient/semiconductorMath";
import type { SemiconductorStock } from "../dataClient/semiconductorTypes";
import { getSemiconductorData } from "../dataClient/staticStockDataClient";
import { usePollingData } from "../dataClient/usePollingData";

type Level = "major" | "middle" | "minor";

function groupLabel(stock: SemiconductorStock, level: Level): string {
  if (level === "major") return stock.major;
  if (level === "middle") return `${stock.major} / ${stock.middle}`;
  return `${stock.major} / ${stock.middle} / ${stock.minor}`;
}

export function SemiconductorTrendsPage() {
  const { data, error, loading, refreshing, lastCheckedAt, refresh } = usePollingData(getSemiconductorData, 300_000);
  const [level, setLevel] = useState<Level>("major");
  const [major, setMajor] = useState("");
  const [period, setPeriod] = useState<Period>(30);
  const [selected, setSelected] = useState("");
  const stocks = data?.stocks ?? [];
  const majors = [...new Set(stocks.map((stock) => stock.major))];
  const groups = useMemo(() => {
    const map = new Map<string, SemiconductorStock[]>();
    for (const stock of stocks) {
      if (major && stock.major !== major) continue;
      const key = groupLabel(stock, level);
      map.set(key, [...(map.get(key) ?? []), stock]);
    }
    return [...map.entries()].sort(([a], [b]) => a.localeCompare(b, "ko"));
  }, [stocks, level, major]);
  const active = groups.find(([name]) => name === selected) ?? groups[0];
  const activeStocks = active?.[1] ?? [];
  const chart = useMemo(() => sectorSeries(activeStocks, period), [activeStocks, period]);
  const ranked = useMemo(() => [...activeStocks].sort((a, b) =>
    (stockReturn(b, period) ?? -Infinity) - (stockReturn(a, period) ?? -Infinity)), [activeStocks, period]);

  return <main className="pageShell semiPage">
    <header className="semiHero"><div><p className="eyebrow">SECTOR PERFORMANCE</p><h1>반도체 섹터 주가 추이</h1>
      <p>7·30·90·180·360일 수익률을 분류별로 비교하고, 구성 종목의 흐름을 확인합니다.</p></div>
      <Link className="semiHeroLink" to="/semiconductors">종목 목록으로 ↗</Link></header>
    <DataRefreshStatus refreshing={refreshing} lastCheckedAt={lastCheckedAt} generatedAt={data?.quoted_at} cadence="semiconductor" onRefresh={refresh} />
    {loading && <LoadingSpinner />}{error && <ErrorNotice message={error} />}
    {data && <>
      <section className="semiPanel semiFilterPanel"><div className="semiPanelHeading"><h2>비교 범위</h2><p>하나의 종목은 대표 소분류 한 곳에 포함됩니다.</p></div>
        <div className="semiFilters semiTrendFilters"><label>분류 단계<select value={level} onChange={(event) => { setLevel(event.target.value as Level); setSelected(""); }}>
          <option value="major">대분류</option><option value="middle">중분류</option><option value="minor">소분류</option></select></label>
          <label>대분류 필터<select value={major} onChange={(event) => { setMajor(event.target.value); setSelected(""); }}><option value="">전체</option>{majors.map((name) => <option key={name}>{name}</option>)}</select></label></div>
      </section>
      <section className="semiPanel"><div className="semiPanelHeading"><h2>섹터별 상승률</h2><p>구성 종목의 조정 종가 수익률을 동일 비중으로 평균했습니다.</p></div>
        <div className="semiTableWrap"><table className="semiTable semiTrendTable"><thead><tr><th>대분류</th><th>중분류</th><th>소분류</th><th>종목 수</th>{PERIODS.map((days) => <th key={days} className="semiNumber">{days}일</th>)}</tr></thead><tbody>
          {groups.map(([name, members]) => <tr key={name} className={active?.[0] === name ? "selected" : ""}>
            <td>{level === "major" ? <button type="button" className="semiTextButton" onClick={() => setSelected(name)}>{members[0].major}</button> : members[0].major}</td>
            <td>{level === "middle" ? <button type="button" className="semiTextButton" onClick={() => setSelected(name)}>{members[0].middle}</button> : level === "minor" ? members[0].middle : "-"}</td>
            <td>{level === "minor" ? <button type="button" className="semiTextButton" onClick={() => setSelected(name)}>{members[0].minor}</button> : "-"}</td>
            <td>{members.length}개</td>
            {PERIODS.map((days) => { const result = sectorReturn(members, days); return <td key={days} className={`semiNumber ${result.value === null ? "" : result.value > 0 ? "semiUp" : result.value < 0 ? "semiDown" : ""}`} title={`${result.count}/${result.total}개 종목 계산 가능`}>
              {formatPercent(result.value)}<small>{result.count}/{result.total}</small></td>; })}</tr>)}
        </tbody></table></div>
      </section>
      {active && <><section className="semiPanel"><div className="semiPanelHeading semiHeadingSplit"><div><h2>{active[0]}</h2><p>{activeStocks.length}개 구성 종목 · 기준값 100 · 동일 비중 평균</p></div>
        <div className="semiPeriodTabs" aria-label="차트 기간">{PERIODS.map((days) => <button key={days} type="button" className={period === days ? "active" : ""} onClick={() => setPeriod(days)}>{days}일</button>)}</div></div>
        <div className="semiTrendHeadline"><strong className={(sectorReturn(activeStocks, period).value ?? 0) >= 0 ? "semiUp" : "semiDown"}>{formatPercent(sectorReturn(activeStocks, period).value)}</strong>
          <span>계산 가능 {sectorReturn(activeStocks, period).count}/{activeStocks.length}개</span></div>
        <SemiconductorLineChart points={chart} title={`${active[0]} ${period}일`} unit="지수" />
      </section>
      <section className="semiPanel"><div className="semiPanelHeading"><h2>구성 종목 수익률</h2><p>{period}일 조정 종가 기준 · 현재가는 종목별 제공 날짜를 함께 표시합니다. 종목을 누르면 가격 차트와 재무 정보를 볼 수 있습니다.</p></div>
        <div className="semiTableWrap"><table className="semiTable semiConstituentTable"><thead><tr><th>종목</th><th>대분류</th><th>중분류</th><th>소분류</th><th>시장</th><th className="semiNumber">현재가</th><th className="semiNumber">등락률</th><th className="semiNumber">시가총액</th><th className="semiNumber">{period}일 수익률</th></tr></thead><tbody>
          {ranked.map((stock) => { const value = stockReturn(stock, period); const latest = effectiveHistory(stock).at(-1); const change = stock.quote.change_pct;
            return <tr key={stock.ticker}><td><Link className="semiStockLink" to={`/semiconductors/${encodeURIComponent(stock.ticker)}`}><strong>{stock.name}</strong><span>{stock.code}</span></Link></td>
              <td>{stock.major}</td><td>{stock.middle}</td><td>{stock.minor}</td><td>{stock.market}</td>
              <td className="semiNumber">{formatWon(stock.quote.price ?? latest?.close)}<small>{stock.quote.provider_time?.slice(0, 10) ?? latest?.date ?? "-"}</small></td>
              <td className={`semiNumber ${change === null ? "" : change > 0 ? "semiUp" : change < 0 ? "semiDown" : ""}`}>{formatPercent(change)}</td>
              <td className="semiNumber">{stock.metrics.marketValue || "-"}</td>
              <td className={`semiNumber ${value === null ? "" : value > 0 ? "semiUp" : value < 0 ? "semiDown" : ""}`}>{formatPercent(value)}</td></tr>; })}
        </tbody></table></div></section></>}
      <p className="semiFootnote">섹터 수익률은 지수나 ETF 수익률이 아닙니다. 각 종목의 기준일 이전 가장 가까운 거래일 대비 조정 종가 수익률을 동일 비중 평균한 값입니다. 상장 기간 부족 또는 가격 누락 종목은 계산에서 제외하며 각 셀에 포함 수를 표시합니다. 가격 출처: Yahoo Finance 일봉, Naver Finance 현재가. 시가총액은 최근 수집값입니다.</p>
    </>}
  </main>;
}
