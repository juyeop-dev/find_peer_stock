import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { DataRefreshStatus } from "../components/DataRefreshStatus";
import { ErrorNotice } from "../components/ErrorNotice";
import { LoadingSpinner } from "../components/LoadingSpinner";
import { SemiconductorLineChart } from "../components/SemiconductorLineChart";
import { PriceWithChange } from "../components/PriceWithChange";
import { getSectorData } from "../dataClient/sectorDataClient";
import { usePollingData } from "../dataClient/usePollingData";
import { formatPercent } from "../dataClient/semiconductorMath";
import { SECTOR_PERIODS, classifiedSectorStock, sectorLabel, sectorMoney, sectorRankings, sortSectorMembers, sortSectors } from "../dataClient/sectorRankings";
import type { SectorLevel, SectorMemberSort, SectorPeriod, SectorSnapshot, SectorSort, SectorStock } from "../dataClient/sectorRankings";
import { loadSectorHistories, sectorHistorySeries } from "../dataClient/sectorExplorer";
import type { SectorHistoryProgress } from "../dataClient/sectorExplorer";
import type { StockHistory } from "../dataClient/stockHistoryClient";
import "../styles/sectorExplorer.css";

type Mode = "stocks" | "trends";
const tone = (value: number | null) => value == null || value === 0 ? "" : value > 0 ? "semiUp" : "semiDown";
const pathFor = (mode: Mode, sector: string) => sector === "semiconductors" ? `/semiconductors${mode === "trends" ? "/trends" : ""}` : `/sector-${mode}?${new URLSearchParams({sector})}`;

export function SectorExplorerPage({mode, semiconductor}: {mode: Mode; semiconductor: ReactNode}) {
  const navigate = useNavigate(), location = useLocation();
  const [params] = useSearchParams();
  const curated = location.pathname.startsWith("/semiconductors");
  const sector = curated ? "semiconductors" : params.get("sector") || "all";
  const state = usePollingData(getSectorData, 300_000);
  const options = useMemo(() => [...new Set(state.data?.stocks.map(stock => classifiedSectorStock(stock).sector) ?? [])].sort((a,b) => sectorLabel(a).localeCompare(sectorLabel(b), "ko")), [state.data]);
  return <>
    <section className="pageShell sectorUniverseSelector" aria-label="섹터 선택">
      <label>탐색할 섹터<select aria-label="탐색할 섹터" value={sector} onChange={event => navigate(pathFor(mode, event.target.value))}>
        <option value="semiconductors">반도체 · 세부 분류</option><option value="all">국내 전체 섹터</option>
        {options.map(key => <option key={key} value={key}>{sectorLabel(key)}</option>)}
      </select></label>
      <p>반도체의 세부 분류와 국내 다른 섹터를 선택해 비교하세요.</p>
      <Link className="semiTextButton" to={pathFor(mode === "stocks" ? "trends" : "stocks", sector)}>{mode === "stocks" ? "선택 섹터 추이 보기 ↗" : "선택 섹터 종목 보기 ↗"}</Link>
    </section>
    {curated ? semiconductor : <DomesticSectorExplorer key={`${mode}:${sector}`} mode={mode} sector={sector} {...state} />}
  </>;
}

interface Props {
  mode: Mode; sector: string; data: SectorSnapshot | null; error: string | null; loading: boolean; refreshing: boolean;
  lastCheckedAt: string | null; lastSourceAt: string | null; refresh: () => void;
}
function DomesticSectorExplorer({mode, sector, data, error, loading, refreshing, lastCheckedAt, lastSourceAt, refresh}: Props) {
  const [params, setParams] = useSearchParams();
  const change = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    value ? next.set(key, value) : next.delete(key);
    if (key === "level" || key === "board") next.delete("group");
    setParams(next, {replace: true});
  };
  const board = ["KOSPI", "KOSDAQ"].includes(params.get("board") ?? "") ? params.get("board")! : "";
  const industry = params.get("industry") ?? "";
  const query = params.get("q") ?? "";
  const level: SectorLevel = params.get("level") === "sector" ? "sector" : "industry";
  const period: SectorPeriod = SECTOR_PERIODS.some(value => value.key === params.get("period")) ? params.get("period") as SectorPeriod : "month";
  const label = SECTOR_PERIODS.find(value => value.key === period)!.label;
  const [memberSort, setMemberSort] = useState<{key: SectorMemberSort; direction: "asc" | "desc"}>({key: mode === "stocks" ? "marketCap" : "return", direction: "desc"});
  const [groupSort, setGroupSort] = useState<{key: SectorSort; direction: "asc" | "desc"}>({key: "return", direction: "desc"});
  const stocks = useMemo(() => (data?.stocks ?? []).map(classifiedSectorStock).filter(stock => stock.date === data?.date && (sector === "all" || stock.sector === sector) && (!board || stock.exchange === board)), [data, sector, board]);
  const industries = useMemo(() => [...new Set(stocks.map(stock => stock.industry))].sort((a,b) => sectorLabel(a).localeCompare(sectorLabel(b), "ko")), [stocks]);
  const groups = useMemo(() => data ? sortSectors(sectorRankings({...data, stocks}, level, period, "", "equal"), groupSort.key, groupSort.direction) : [], [data, stocks, level, period, groupSort]);
  // Reordering the ranking must not change the user's active sector.
  const defaultGroup = useMemo(() => [...groups].sort((a,b) => a.name.localeCompare(b.name, "ko"))[0], [groups]);
  const active = groups.find(group => group.key === params.get("group")) ?? defaultGroup;
  const members = useMemo(() => sortSectorMembers((mode === "trends" ? active?.members ?? [] : stocks).filter(stock => (!industry || mode === "trends" || stock.industry === industry) && (!query.trim() || `${stock.name} ${stock.code} ${sectorLabel(stock.industry)}`.toLowerCase().includes(query.trim().toLowerCase()))), memberSort.key, memberSort.direction, period), [stocks, active, mode, industry, query, memberSort, period]);
  const [histories, setHistories] = useState<StockHistory[]>([]);
  const [progress, setProgress] = useState<SectorHistoryProgress>();
  const [chartLoading, setChartLoading] = useState(false);
  const [refreshVersion, setRefreshVersion] = useState(0);
  const consumedRefresh = useRef(0);
  const chartStocks = active?.members ?? [];
  const membership = chartStocks.map(stock => stock.ticker).sort().join(",");
  const currentStocks = useRef(chartStocks); currentStocks.current = chartStocks;
  const loadHistories = useCallback((signal: AbortSignal, live: boolean) => loadSectorHistories(currentStocks.current, signal, live, setProgress), []);
  useEffect(() => {
    if (mode !== "trends" || !membership) return;
    const controller = new AbortController();
    const live = refreshVersion !== consumedRefresh.current;
    consumedRefresh.current = refreshVersion;
    setHistories([]); setChartLoading(true); setProgress({checked: 0, total: currentStocks.current.length, errors: 0});
    loadHistories(controller.signal, live).then(result => {
      if (!controller.signal.aborted) setHistories(result.values);
    }).catch(() => {}).finally(() => { if (!controller.signal.aborted) setChartLoading(false); });
    return () => controller.abort();
  }, [mode, membership, data?.date, refreshVersion, loadHistories]);
  const chart = useMemo(() => data ? sectorHistorySeries(histories, period, data.date) : null, [histories, period, data]);
  const title = sector === "all" ? "국내 전체 섹터" : sectorLabel(sector);
  const returnTo = `/sector-${mode}?${params}`;
  const stockLink = (stock: SectorStock) => `/market-stocks/${encodeURIComponent(stock.ticker)}?${new URLSearchParams({source: "sectors", market: "korea", date: stock.date, returnTo})}`;
  function memberHeading(key: SectorMemberSort, text: string) {
    const active = memberSort.key === key;
    return <th scope="col" className={["name", "exchange"].includes(key) ? "" : "semiNumber"} aria-sort={active ? memberSort.direction === "asc" ? "ascending" : "descending" : "none"}><button className="semiSortButton" onClick={() => setMemberSort({key, direction: active && memberSort.direction === "desc" ? "asc" : "desc"})}>{text}<span aria-hidden="true">{active ? memberSort.direction === "asc" ? "↑" : "↓" : "↕"}</span></button></th>;
  }
  const periodTabs = <div className="semiPeriodTabs" aria-label="수익률 기간">{SECTOR_PERIODS.map(item => <button key={item.key} className={period === item.key ? "active" : ""} onClick={() => change("period", item.key)}>{item.label}</button>)}</div>;
  return <main className="pageShell semiPage domesticSectorExplorer">
    <header className="semiHero"><div><p className="eyebrow">KOREA SECTOR EXPLORER</p><h1>{title} {mode === "stocks" ? "종목" : "주가 추이"}</h1><p>섹터와 업종을 선택해 구성 종목의 가격·거래대금·수익률을 비교합니다.</p></div><Link className="semiHeroLink" to="/sectors">섹터 상승률 · 캘린더 ↗</Link></header>
    <DataRefreshStatus cadence="sectors" generatedAt={data?.fetched_at} refreshing={refreshing || chartLoading && refreshVersion > 0} lastCheckedAt={lastCheckedAt} lastSourceAt={lastSourceAt} onRefresh={() => {refresh(); if (mode === "trends") setRefreshVersion(value => value + 1);}} />
    {loading && <LoadingSpinner />}{error && <ErrorNotice message={error} />}
    {data && <>
      <section className="semiPanel"><div className="semiFilters">
        {mode === "trends" ? <label>분류 단계<select value={level} onChange={event => change("level", event.target.value)}><option value="industry">세부 업종</option><option value="sector">대분류</option></select></label> : <label>업종<select value={industry} onChange={event => change("industry", event.target.value)}><option value="">전체 업종</option>{industries.map(item => <option key={item} value={item}>{sectorLabel(item)}</option>)}</select></label>}
        <label>시장<select value={board} onChange={event => change("board", event.target.value)}><option value="">KOSPI + KOSDAQ</option><option>KOSPI</option><option>KOSDAQ</option></select></label>
        <label>종목 검색<input value={query} onChange={event => change("q", event.target.value)} placeholder="종목명 · 코드 · 업종" /></label>
      </div></section>
      {mode === "trends" && <section className="semiPanel"><div className="semiPanelHeading semiHeadingSplit"><div><h2>섹터별 수익률</h2><p>현재 구성 종목의 동일 비중 평균 · {data.date}</p></div>{periodTabs}</div><div className="semiTableWrap"><table className="semiTable sectorExplorerGroups"><thead><tr><th scope="col">섹터 · 업종</th>{([['count','종목 수'],['return',`${label} 수익률`],['turnover','거래대금'],['marketCap','시가총액']] as const).map(([key,text]) => <th key={key} className="semiNumber" scope="col" aria-sort={groupSort.key === key ? groupSort.direction === "asc" ? "ascending" : "descending" : "none"}><button className="semiSortButton" onClick={() => setGroupSort({key, direction: groupSort.key === key && groupSort.direction === "desc" ? "asc" : "desc"})}>{text}<span aria-hidden="true">{groupSort.key === key ? groupSort.direction === "asc" ? "↑" : "↓" : "↕"}</span></button></th>)}</tr></thead><tbody>{groups.map(group => <tr key={group.key} className={active?.key === group.key ? "selected" : ""}><th scope="row"><button className="semiTextButton" aria-pressed={active?.key === group.key} onClick={() => change("group", group.key)}>{group.name}</button></th><td className="semiNumber">{group.members.length}개</td><td className={`semiNumber ${tone(group.value)}`}>{formatPercent(group.value)}<small>{group.returnCount}/{group.members.length}개 계산</small></td><td className="semiNumber">{sectorMoney(group.turnover)}</td><td className="semiNumber">{sectorMoney(group.marketCap)}</td></tr>)}</tbody></table></div></section>}
      {mode === "trends" && active && <section className="semiPanel sectorExplorerChart"><div className="semiPanelHeading semiHeadingSplit"><div><h2>{active.name} 주가 추이</h2><p>기준값 100 · 조정 종가 동일 비중 · {chart?.count ?? 0}/{active.members.length}개 종목 계산</p></div>{periodTabs}</div>
        {chartLoading ? <p role="status">일봉 조회 중 {progress?.checked ?? 0}/{progress?.total ?? 0}종목</p> : <SemiconductorLineChart points={chart?.points ?? []} title={`${active.name} ${label} 추이`} unit="지수" />}
        {progress && progress.errors > 0 && <p className="semiFootnote" role="status">{progress.errors}종목의 일봉 조회에 실패했습니다. 이전에 확인한 이력이 있으면 유지합니다.</p>}
        <p className="semiFootnote">현재 구성 종목 중 시작일 이전 가격과 {data.date} 종가가 모두 확인된 종목만 기간 전체에 동일 비중으로 반영합니다. 신규 상장·이력 부족 종목은 제외합니다. 차트 비교 기간은 1주 7일·1개월 30일·3개월 90일·1년 달력 기준이며, 제공처의 기간 수익률과 다를 수 있습니다.</p>
      </section>}
      <section className="semiPanel"><div className="semiPanelHeading semiHeadingSplit"><div><h2>{mode === "trends" ? `${active?.name ?? "선택 섹터"} 구성 종목` : "종목별 가격"}</h2><p>{members.length}개 종목 · {data.date} 기준 · 종목을 선택하면 주가·실적 상세 정보를 확인합니다.</p></div>{mode === "stocks" && periodTabs}</div>
        <div className="semiTableWrap"><table className="semiTable sectorExplorerMembers"><thead><tr>{memberHeading("name", "종목")}<th scope="col">섹터 · 업종</th>{memberHeading("exchange", "시장")}{memberHeading("price", "최근 가격")}{memberHeading("return", `${label} 수익률`)}{memberHeading("turnover", "거래대금")}{memberHeading("marketCap", "시가총액")}</tr></thead><tbody>{members.map(stock => <tr key={stock.ticker}><th scope="row"><Link className="semiStockLink" to={stockLink(stock)}><strong>{stock.name}</strong><span>{stock.code}</span></Link></th><td>{sectorLabel(stock.sector)}<small>{sectorLabel(stock.industry)}</small></td><td>{stock.exchange}</td><td className="semiNumber"><PriceWithChange price={stock.price} change={stock.change_pct} /></td><td className={`semiNumber ${tone(stock.returns[period])}`}>{formatPercent(stock.returns[period])}</td><td className="semiNumber">{sectorMoney(stock.turnover)}</td><td className="semiNumber">{sectorMoney(stock.market_cap)}</td></tr>)}</tbody></table></div>
        {!members.length && <p className="semiEmpty">조건에 맞는 종목이 없습니다.</p>}
      </section>
      <p className="semiFootnote">{data.universe}. 최근 거래일이 다른 종목은 제외합니다. 섹터·업종은 현재 사업 분류 보정 기준이며 과거 공식 편입 목록을 뜻하지 않습니다. 시가총액과 거래대금은 조회 시점 제공값입니다. 새로고침은 목록의 원본 시세를 다시 조회하며, 추이 화면에서는 선택 그룹의 일봉도 다시 가져옵니다.</p>
    </>}
  </main>;
}
