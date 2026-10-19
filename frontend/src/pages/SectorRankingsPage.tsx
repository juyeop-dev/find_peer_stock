import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { DataRefreshStatus } from "../components/DataRefreshStatus";
import { ErrorNotice } from "../components/ErrorNotice";
import { LoadingSpinner } from "../components/LoadingSpinner";
import { getSectorData } from "../dataClient/sectorDataClient";
import { usePollingData } from "../dataClient/usePollingData";
import { formatDateTime } from "../dataClient/formatters";
import { formatPercent } from "../dataClient/semiconductorMath";
import { SECTOR_PERIODS, sectorIcon, sectorLabel, sectorMoney, sectorRankings, sortSectors } from "../dataClient/sectorRankings";
import type { SectorLevel, SectorPeriod, SectorSort, SectorStock } from "../dataClient/sectorRankings";
import "../styles/sectorRankings.css";

const tone = (value: number | null) => value === null || value === 0 ? "" : value > 0 ? "semiUp" : "semiDown";
export function SectorRankingsPage() {
  const { data, loading, error, refreshing, lastCheckedAt, lastSourceAt, refresh } = usePollingData(getSectorData, 300_000);
  const [params, setParams] = useSearchParams();
  const level: SectorLevel = params.get("level") === "sector" ? "sector" : "industry";
  const period: SectorPeriod = SECTOR_PERIODS.some(item => item.key === params.get("period")) ? params.get("period") as SectorPeriod : "day";
  const board = ["KOSPI", "KOSDAQ"].includes(params.get("board") ?? "") ? params.get("board")! : "";
  const selected = params.get("selected") ?? "";
  const search = params.get("q") ?? "";
  const [sort, setSort] = useState<{ key: SectorSort; direction: "asc" | "desc" }>({ key: "turnover", direction: "desc" });
  function change(key: string, value: string) {
    const next = new URLSearchParams(params);
    value ? next.set(key, value) : next.delete(key);
    if (key === "level" || key === "board") next.delete("selected");
    setParams(next, { replace: true });
  }
  const groups = useMemo(() => data ? sectorRankings(data, level, period, board) : [], [data, level, period, board]);
  const ranked = useMemo(() => sortSectors(groups.filter(group => !search.trim() || `${group.name} ${group.key} ${group.members.map(stock => `${stock.name} ${stock.code}`).join(" ")}`.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase())), sort.key, sort.direction), [groups, search, sort]);
  const active = ranked.find(group => group.key === selected) ?? ranked[0];
  const members = useMemo(() => [...(active?.members ?? [])].sort((a, b) => {
    const x = a.returns[period], y = b.returns[period];
    return x === null ? y === null ? a.ticker.localeCompare(b.ticker) : 1 : y === null ? -1 : y - x || (b.turnover ?? -1) - (a.turnover ?? -1) || a.ticker.localeCompare(b.ticker);
  }), [active, period]);
  const periodLabel = SECTOR_PERIODS.find(item => item.key === period)!.label;
  const latestStocks = data?.stocks.filter(stock => stock.date === data.date && (!board || stock.exchange === board)) ?? [];
  const returnTo = `/sectors${params.size ? `?${params}` : ""}`;
  const stockLink = (stock: SectorStock) => `/market-stocks/${encodeURIComponent(stock.ticker)}?${new URLSearchParams({ source: "sectors", market: "korea", date: stock.date, returnTo })}`;
  function heading(key: SectorSort, label: string) {
    const active = sort.key === key;
    return <th scope="col" className="semiNumber" aria-sort={active ? sort.direction === "desc" ? "descending" : "ascending" : "none"}>
      <button className={`semiSortButton ${active ? "active" : ""}`} onClick={() => setSort({ key, direction: active && sort.direction === "desc" ? "asc" : "desc" })}>
        {label}<span aria-hidden="true">{active ? sort.direction === "desc" ? "↓" : "↑" : "↕"}</span>
      </button></th>;
  }
  return <main className="pageShell semiPage sectorRankingsPage">
    <header className="sectorHero"><div><p className="eyebrow">SECTOR RANKING</p><h1>국내 섹터 상승률</h1><p>어느 업종이 오르고, 어디에 거래가 모이는지 한눈에 비교하세요.</p></div><Link className="semiTextButton" to="/semiconductors/trends">반도체 세부 섹터 추이 ↗</Link></header>
    <DataRefreshStatus cadence="sectors" generatedAt={data?.fetched_at} lastCheckedAt={lastCheckedAt} lastSourceAt={lastSourceAt} refreshing={refreshing} onRefresh={refresh} />
    {loading && <LoadingSpinner />}{error && <ErrorNotice message={error} />}
    {data && <>
      <div className="sectorSummary" aria-label="집계 요약"><div><span>거래일</span><strong>{data.date}</strong></div><div><span>집계 종목</span><strong>{latestStocks.length.toLocaleString("ko-KR")}개</strong></div><div><span>상승 / 하락 섹터</span><strong><b className="semiUp">{groups.filter(group => (group.value ?? 0) > 0).length}</b><span> / </span><b className="semiDown">{groups.filter(group => (group.value ?? 0) < 0).length}</b></strong></div><div><span>전체 거래대금</span><strong>{sectorMoney(groups.some(group => group.turnover !== null) ? groups.reduce((sum, group) => sum + (group.turnover ?? 0), 0) : null)}</strong></div></div>
      <section className="semiPanel sectorRankingPanel" aria-label="섹터별 순위">
        <div className="sectorControls"><div className="semiPeriodTabs" aria-label="수익률 기간">{SECTOR_PERIODS.map(item => <button key={item.key} className={period === item.key ? "active" : ""} aria-pressed={period === item.key} onClick={() => change("period", item.key)}>{item.label}</button>)}</div>
          <div className="sectorFilters"><label>분류<select value={level} onChange={event => change("level", event.target.value)}><option value="industry">세부 업종</option><option value="sector">대분류</option></select></label><label>시장<select value={board} onChange={event => change("board", event.target.value)}><option value="">KOSPI + KOSDAQ</option><option>KOSPI</option><option>KOSDAQ</option></select></label><label className="sectorSearch"><span className="sectorSrOnly">섹터·종목 검색</span><input type="search" placeholder="섹터·종목 검색" value={search} onChange={event => change("q", event.target.value)} /></label></div></div>
        <div className="sectorTableCaption"><p><strong>{ranked.length}개 섹터</strong> · {periodLabel} 등락률 · 동일 비중 평균</p><span>조회 {formatDateTime(data.fetched_at)}</span></div>
        <div className="semiTableWrap"><table className="semiTable sectorRankingTable"><caption className="sectorSrOnly">{periodLabel} 국내 섹터 수익률 순위. 섹터 이름을 선택하면 구성 종목을 볼 수 있습니다.</caption><thead><tr><th scope="col">순위</th><th scope="col">섹터</th>{heading("return", "등락률")}{heading("turnover", "거래대금")}{heading("marketCap", "시가총액")}<th scope="col">대표 종목</th>{heading("count", "종목 수")}</tr></thead><tbody>
          {ranked.map((group, index) => <tr key={group.key} className={active?.key === group.key ? "selected" : ""}><td className="sectorRank">{index + 1}</td><th scope="row"><button className="sectorNameButton" aria-pressed={active?.key === group.key} aria-controls="sector-constituents" onClick={() => change("selected", group.key)}><span className="sectorIcon" aria-hidden="true">{sectorIcon(group.sector)}</span><span>{group.name}</span></button></th>
            <td className={`semiNumber sectorReturn ${tone(group.value)}`} title={`${group.returnCount}/${group.members.length}종목 계산 가능`}>{formatPercent(group.value)}{group.returnCount !== group.members.length && <small>{group.returnCount}/{group.members.length}개</small>}</td>
            <td className="semiNumber">{sectorMoney(group.turnover)}{group.turnoverCount !== group.members.length && <small>{group.turnoverCount}/{group.members.length}개 제공</small>}</td><td className="semiNumber">{sectorMoney(group.marketCap)}{group.capCount !== group.members.length && <small>{group.capCount}/{group.members.length}개 제공</small>}</td>
            <td><Link className="sectorRepresentative" to={stockLink(group.representative)}><span className="sectorCompanyBadge" aria-hidden="true">{group.representative.name.slice(0, 2)}</span><span>{group.representative.name}{group.members.length > 1 ? <small>외 {group.members.length - 1}개</small> : null}</span></Link></td><td className="semiNumber"><button className="semiTextButton" onClick={() => change("selected", group.key)} aria-label={`${group.name} ${group.members.length}개 구성 종목 보기`}>{group.members.length}개</button></td></tr>)}
        </tbody></table></div>
        {!ranked.length && <p className="semiEmpty" role="status">검색 조건에 맞는 섹터가 없습니다.</p>}
        <p className="semiFootnote">{data.universe}. {data.stale_count ? `최신 거래일 자료가 없는 ${data.stale_count}종목은 순위에서 제외했습니다. ` : ""}등락률이 없는 종목은 평균에서 제외하고, 금액 미제공 시 집계된 종목 수를 표시합니다.</p>
      </section>
      {active && <section id="sector-constituents" className="semiPanel sectorConstituents" aria-label={`${active.name} 구성 종목`}><div className="semiPanelHeading semiHeadingSplit"><div><p className="eyebrow">{sectorLabel(active.sector)}</p><h2>{active.name} 구성 종목</h2><p>{members.length}개 · {periodLabel} 등락률순 · 종목을 선택하면 주가·실적 상세 화면으로 이동합니다.</p></div><strong className={`sectorSelectedReturn ${tone(active.value)}`}>{formatPercent(active.value)}</strong></div>
        <div className="semiTableWrap"><table className="semiTable sectorMemberTable"><thead><tr><th scope="col">종목</th><th scope="col">시장</th><th scope="col" className="semiNumber">최근 가격</th><th scope="col" className="semiNumber">{periodLabel} 등락률</th><th scope="col" className="semiNumber">거래대금</th><th scope="col" className="semiNumber">시가총액</th></tr></thead><tbody>{members.map(stock => <tr key={stock.ticker}><th scope="row"><Link className="semiStockLink" to={stockLink(stock)}><strong>{stock.name}</strong><span>{stock.code}</span></Link></th><td>{stock.exchange}</td><td className="semiNumber">{stock.price.toLocaleString("ko-KR")}원</td><td className={`semiNumber ${tone(stock.returns[period])}`}>{formatPercent(stock.returns[period])}</td><td className="semiNumber">{sectorMoney(stock.turnover)}</td><td className="semiNumber">{sectorMoney(stock.market_cap)}</td></tr>)}</tbody></table></div>
      </section>}
      <p className="semiFootnote sectorMethodology">등락률은 같은 거래일의 구성 종목 수익률을 동일 비중으로 평균한 값이며 지수 수익률과 다릅니다. 기간 선택은 등락률에 적용하고, 거래대금은 해당 거래일 값, 시가총액은 조회 시점 제공값의 합계입니다. 대표 종목은 제공 시가총액이 가장 큰 종목입니다. 업종은 <a href={data.source_url} target="_blank" rel="noreferrer">TradingView 분류</a> 기준으로 이미지의 테마 분류와 다를 수 있습니다. 새로고침은 국내 전체 목록을 원본에서 다시 조회합니다.</p>
    </>}
  </main>;
}
