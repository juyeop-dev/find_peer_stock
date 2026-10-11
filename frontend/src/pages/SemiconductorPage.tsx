import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { DataRefreshStatus } from "../components/DataRefreshStatus";
import { ErrorNotice } from "../components/ErrorNotice";
import { LoadingSpinner } from "../components/LoadingSpinner";
import { formatDateTime } from "../dataClient/formatters";
import { effectiveHistory, formatPercent, formatWon, PERIODS, priceOnDate, stockReturn } from "../dataClient/semiconductorMath";
import type { Period } from "../dataClient/semiconductorMath";
import type { SemiconductorStock } from "../dataClient/semiconductorTypes";
import { getSemiconductorData } from "../dataClient/staticStockDataClient";
import { usePollingData } from "../dataClient/usePollingData";

function dayChange(stock: SemiconductorStock, date: string): number | null {
  const history = effectiveHistory(stock);
  const index = history.findIndex((point) => point.date === date);
  if (index <= 0 || history[index - 1].close <= 0) return null;
  return (history[index].close / history[index - 1].close - 1) * 100;
}

export function SemiconductorPage() {
  const { data, error, loading, refreshing, lastCheckedAt, refresh } = usePollingData(getSemiconductorData, 300_000);
  const [major, setMajor] = useState("");
  const [middle, setMiddle] = useState("");
  const [minor, setMinor] = useState("");
  const [market, setMarket] = useState("");
  const [query, setQuery] = useState("");
  const [date, setDate] = useState("latest");
  const [period, setPeriod] = useState<Period>(30);
  const stocks = data?.stocks ?? [];
  const majors = [...new Set(stocks.map((stock) => stock.major))];
  const middles = [...new Set(stocks.filter((stock) => !major || stock.major === major).map((stock) => stock.middle))];
  const minors = [...new Set(stocks.filter((stock) => (!major || stock.major === major) && (!middle || stock.middle === middle)).map((stock) => stock.minor))];
  const dates = useMemo(() => [...new Set(stocks.flatMap((stock) => effectiveHistory(stock).map((point) => point.date)))].sort().reverse(), [stocks]);
  const visible = useMemo(() => stocks.filter((stock) =>
    (!major || stock.major === major) && (!middle || stock.middle === middle) &&
    (!minor || stock.minor === minor) && (!market || stock.market === market) &&
    (!query || `${stock.name} ${stock.code} ${stock.minor}`.toLowerCase().includes(query.toLowerCase()))
  ).sort((a, b) => a.name.localeCompare(b.name, "ko")), [stocks, major, middle, minor, market, query]);

  return <main className="pageShell semiPage">
    <header className="semiHero">
      <div><p className="eyebrow">KOREA SEMICONDUCTOR MAP</p><h1>국내 반도체 종목</h1>
        <p>대분류 → 중분류 → 소분류로 탐색하고, 선택한 날짜의 가격과 기간 수익률을 비교합니다.</p></div>
      <Link className="semiHeroLink" to="/semiconductors/trends">섹터 주가 추이 보기 ↗</Link>
    </header>
    <DataRefreshStatus refreshing={refreshing} lastCheckedAt={lastCheckedAt} generatedAt={data?.quoted_at} cadence="semiconductor" onRefresh={refresh} />
    {loading && <LoadingSpinner />}{error && <ErrorNotice message={error} />}
    {data && <>
      <div className="semiSummaryStrip">
        <div><span>분류 종목</span><strong>{stocks.length}개</strong></div>
        <div><span>현재가 수집</span><strong>{stocks.filter((stock) => stock.quote.status === "ok").length}개</strong></div>
        <div><span>가격 조회 시각</span><strong>{formatDateTime(data.quoted_at)}</strong></div>
      </div>
      <section className="semiPanel semiFilterPanel" aria-label="종목 필터">
        <div className="semiPanelHeading"><h2>섹터 탐색</h2><p>주 사업 기준 대표 분류이며 복수 사업 기업은 한 곳에만 포함됩니다.</p></div>
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
        <div className="semiTableWrap"><table className="semiTable"><thead><tr><th>종목</th><th>분류</th><th>시장</th><th>가격</th><th>기준일</th><th>등락률</th><th>{period}일 수익률</th></tr></thead><tbody>
          {visible.map((stock) => {
            const point = date === "latest" ? effectiveHistory(stock).at(-1) : priceOnDate(stock, date);
            const price = date === "latest" ? stock.quote.price ?? point?.close : point?.close;
            const change = date === "latest" ? stock.quote.change_pct : dayChange(stock, date);
            const gain = date !== "latest" && !point ? null : stockReturn(stock, period, date === "latest" ? undefined : date);
            return <tr key={stock.ticker}><td><Link className="semiStockLink" to={`/semiconductors/${encodeURIComponent(stock.ticker)}`}><strong>{stock.name}</strong><span>{stock.code}</span></Link></td>
              <td><span className="semiClass">{stock.major} / {stock.middle}</span><small>{stock.minor}</small></td><td>{stock.market}</td>
              <td className="semiNumber">{formatWon(price)}</td><td>{date === "latest" ? stock.quote.provider_time?.slice(0, 10) ?? point?.date ?? "-" : point?.date ?? "-"}</td>
              <td className={`semiNumber ${change === null || change === undefined ? "" : change > 0 ? "semiUp" : change < 0 ? "semiDown" : ""}`}>{formatPercent(change)}</td>
              <td className={`semiNumber ${gain === null ? "" : gain > 0 ? "semiUp" : gain < 0 ? "semiDown" : ""}`}>{formatPercent(gain)}</td></tr>;
          })}
        </tbody></table>{visible.length === 0 && <p className="semiEmpty">조건에 맞는 종목이 없습니다.</p>}</div>
      </section>
      <p className="semiFootnote">가격: Naver Finance 현재가 / Yahoo Finance 일봉. 수익률은 배당·분할 조정 종가 기준이며, 기준 날짜 이전 가장 가까운 거래일과 비교합니다. 현재가는 실시간 체결가가 아니며 제공처 기준 시각을 확인하세요.</p>
    </>}
  </main>;
}
