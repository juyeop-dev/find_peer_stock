import { useMemo, useState } from "react";
import { SemiconductorLineChart } from "../components/SemiconductorLineChart";
import { DataRefreshStatus } from "../components/DataRefreshStatus";
import { ErrorNotice } from "../components/ErrorNotice";
import { LoadingSpinner } from "../components/LoadingSpinner";
import { formatDateTime } from "../dataClient/formatters";
import { formatPercent, PERIODS } from "../dataClient/semiconductorMath";
import type { Period } from "../dataClient/semiconductorMath";
import type { CreditPoint } from "../dataClient/creditTypes";
import { getCreditData } from "../dataClient/staticStockDataClient";
import { usePollingData } from "../dataClient/usePollingData";

type Market = "total" | "kospi" | "kosdaq";
const MARKETS: { key: Market; label: string }[] = [
  { key: "total", label: "전체" }, { key: "kospi", label: "코스피" }, { key: "kosdaq", label: "코스닥" },
];
const trillion = (millions: number) => `${(millions / 1_000_000).toFixed(3)}조원`;

function periodHistory(history: CreditPoint[], days: number): CreditPoint[] {
  const last = history.at(-1);
  if (!last) return [];
  const start = new Date(`${last.date}T12:00:00Z`);
  start.setUTCDate(start.getUTCDate() - days);
  const anchor = start.toISOString().slice(0, 10);
  let startIndex = 0;
  for (let index = 0; index < history.length && history[index].date <= anchor; index += 1) {
    startIndex = index;
  }
  return history.slice(Math.max(startIndex, 0));
}

export function CreditBalancePage() {
  const { data, error, loading, refreshing, lastCheckedAt, lastSourceAt, refresh } = usePollingData(getCreditData, 300_000);
  const [market, setMarket] = useState<Market>("total");
  const [period, setPeriod] = useState<Period>(90);
  const history = data?.history ?? [];
  const latest = history.at(-1);
  const previous = history.at(-2);
  const selectedLabel = MARKETS.find((item) => item.key === market)?.label ?? "전체";
  const visible = useMemo(() => periodHistory(history, period), [history, period]);
  const chart = useMemo(() => visible.map((point) => ({ date: point.date, value: point[market] / 1_000_000 })), [visible, market]);
  const first = visible[0];
  const change = first && latest && first[market] > 0 ? (latest[market] / first[market] - 1) * 100 : null;
  const dailyChange = latest && previous ? latest[market] - previous[market] : null;

  return <main className="pageShell semiPage creditPage">
    <header className="semiHero"><div><p className="eyebrow">MARGIN BALANCE</p><h1>신용 잔고 추이</h1>
      <p>신용거래융자 잔고를 전체·코스피·코스닥별로 살펴봅니다. 기준일은 금융투자협회 통계의 거래일입니다.</p></div></header>
    <DataRefreshStatus refreshing={refreshing} lastCheckedAt={lastCheckedAt} lastSourceAt={lastSourceAt} cadence="credit" onRefresh={refresh} />
    {loading && <LoadingSpinner />}{error && <ErrorNotice message={error} />}
    {data && latest && <>
      <div className="semiSummaryStrip creditSummaryStrip">{MARKETS.map(({ key, label }) => <button key={key} type="button"
        className={market === key ? "active" : ""} onClick={() => setMarket(key)} aria-pressed={market === key}>
        <span>{label} 신용융자 잔고</span><strong>{trillion(latest[key])}</strong>
        <small>{latest.date} 기준</small>
      </button>)}</div>
      <section className="semiPanel"><div className="semiPanelHeading semiHeadingSplit"><div><h2>{selectedLabel} 신용 잔고</h2>
        <p>단위: 조원 · 최근 {period}일 · 거래일별 발표값</p></div>
        <div className="semiPeriodTabs" aria-label="신용 잔고 차트 기간">{PERIODS.map((days) => <button key={days} type="button"
          className={period === days ? "active" : ""} onClick={() => setPeriod(days)}>{days}일</button>)}</div></div>
        <div className="creditHeadline"><strong>{trillion(latest[market])}</strong>
          <span className={(dailyChange ?? 0) >= 0 ? "semiUp" : "semiDown"}>전 거래일 대비 {dailyChange === null ? "-" : `${dailyChange > 0 ? "+" : ""}${trillion(dailyChange)}`}</span>
          <span>{period}일 변화 {formatPercent(change)}</span></div>
        <SemiconductorLineChart points={chart} title={`${selectedLabel} 신용거래융자 잔고`} unit="조원" />
      </section>
      <section className="semiPanel"><div className="semiPanelHeading"><h2>최근 일별 잔고</h2>
        <p>전체는 코스피와 코스닥의 합계입니다. 각 행은 해당 거래일의 잔고입니다.</p></div>
        <div className="semiTableWrap"><table className="semiTable creditTable"><thead><tr>
          <th>기준일</th><th className="semiNumber">전체</th><th className="semiNumber">코스피</th><th className="semiNumber">코스닥</th>
        </tr></thead><tbody>{[...history].reverse().slice(0, 30).map((point) => <tr key={point.date}>
          <td>{point.date}</td><td className="semiNumber">{trillion(point.total)}</td>
          <td className="semiNumber">{trillion(point.kospi)}</td><td className="semiNumber">{trillion(point.kosdaq)}</td>
        </tr>)}</tbody></table></div>
      </section>
      <p className="semiFootnote">자료: <a href={data.source_url} target="_blank" rel="noreferrer">금융투자협회 FreeSIS 신용공여 잔고 추이</a>의 신용거래융자 잔고.
        신용거래대주·예탁증권담보융자·미수금은 포함하지 않습니다. 최신 기준일 {data.latest_date}, 수집 {formatDateTime(data.generated_at)}.
        제공처 발표 시차로 최근 거래일 수치가 아직 없을 수 있습니다.</p>
    </>}
  </main>;
}
