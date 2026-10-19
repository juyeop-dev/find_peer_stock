import { useCallback, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { ErrorNotice } from "../components/ErrorNotice";
import { LoadingSpinner } from "../components/LoadingSpinner";
import { PeriodReturns } from "../components/PeriodReturns";
import { TradingViewWidget } from "../components/TradingViewWidget";
import { SemiconductorLineChart } from "../components/SemiconductorLineChart";
import { getCalendarStockPrices, getNewHighReport, getTurnoverReport } from "../dataClient/staticStockDataClient";
import { usePollingData } from "../dataClient/usePollingData";
import { calendarReturnLink, tradingViewSymbol, tradingViewUrl } from "../dataClient/stockDetailLinks";
import { getExternalQuoteLink } from "../dataClient/externalLinks";
import { formatMarketCap } from "../dataClient/formatters";
import { formatHistoryMoney } from "../dataClient/calendarHistory";
import { formatPercent, PERIODS } from "../dataClient/semiconductorMath";
import type { Period } from "../dataClient/semiconductorMath";
import "../styles/marketStock.css";
import { DataRefreshStatus } from "../components/DataRefreshStatus";
import { RecentFinancialSummary } from "../components/RecentFinancials";
import { FinancialTable } from "./SemiconductorStockPage";
import { liveDetailFor, liveQuoteFor, refreshDetails } from "../dataClient/liveStockDataClient";

const MARKET_CURRENCIES: Record<string, string> = { korea: "KRW", us: "USD", japan: "JPY", taiwan: "TWD", china: "CNY", europe: "EUR" };

function validDate(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const parsed = new Date(`${value}T00:00:00Z`);
  return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
}

function priceLabel(price: number | null | undefined, currency: string): string {
  return price == null ? "미등록" : `${new Intl.NumberFormat("ko-KR", { maximumFractionDigits: currency === "KRW" || currency === "JPY" ? 0 : 4 }).format(price)} ${currency}`;
}

export function MarketStockPage() {
  const { ticker = "" } = useParams();
  const [params] = useSearchParams();
  const [period, setPeriod] = useState<Period>(90);
  const [showFullChart, setShowFullChart] = useState(false);
  const source = params.get("source") === "turnover" ? "turnover" : "new-highs";
  const market = params.get("market") ?? "";
  const date = params.get("date") ?? "";
  const contextValid = validDate(date) && Object.hasOwn(MARKET_CURRENCIES, market);
  const fallback = `/${source}?${new URLSearchParams({ market, date })}`;
  const back = calendarReturnLink(params.get("returnTo"), contextValid ? fallback : `/${source}`);
  const sourceLabel = source === "new-highs" ? "신고가 캘린더" : "거래대금 캘린더";
  const loadStock = useCallback(async (signal: AbortSignal, fromSource = false) => {
    const report = source === "new-highs" ? await getNewHighReport(market, date, signal) : await getTurnoverReport(market, date, signal);
    if (report.market !== market || report.date !== date) throw new Error("선택한 날짜의 기록과 일치하지 않습니다.");
    const stock = report.entries.find((item) => item.ticker.toUpperCase() === ticker.toUpperCase());
    if (!stock) throw new Error("선택한 날짜의 캘린더에서 이 종목을 찾을 수 없습니다.");
    const metadata = fromSource ? await refreshDetails([{ ticker, exchange: stock.exchange }], signal) : {};
    return { stock, source, market, date, ...metadata };
  }, [source, market, date, ticker]);
  const { data, error, loading, refreshing, lastCheckedAt, lastSourceAt, refresh } = usePollingData(contextValid && ticker ? loadStock : null);
  const stock = data?.source === source && data.market === market && data.date === date && data.stock.ticker.toUpperCase() === ticker.toUpperCase() ? data.stock : null;
  const sourceDetail = liveDetailFor(ticker);
  const currentQuote = liveQuoteFor(ticker);
  const currency = currentQuote?.currency ?? stock?.currency ?? (stock?.exchange === "LSE" ? "GBP" : stock?.exchange === "SIX" ? "CHF" : MARKET_CURRENCIES[market]) ?? "";
  const recordedPrice = stock && "price" in stock ? stock.price : stock && "session_close" in stock ? stock.session_close : null;
  const price = currentQuote?.price ?? recordedPrice;
  const category = stock && "category" in stock ? stock.category : stock && "industry" in stock ? stock.industry : "";
  const symbol = stock ? tradingViewSymbol(stock.ticker, stock.exchange) : null;
  const quote = getExternalQuoteLink(ticker);
  const loadPrices = useCallback((signal: AbortSignal) => getCalendarStockPrices(market, ticker.toUpperCase(), signal), [market, ticker]);
  const { data: prices, error: pricesError, loading: pricesLoading, refresh: refreshPrices, reload: reloadPrices } = usePollingData(contextValid ? loadPrices : null);
  const chartDate = sourceDetail?.history?.at(-1)?.date ?? date;
  const since = new Date(`${chartDate || "2000-01-01"}T00:00:00Z`);
  since.setUTCDate(since.getUTCDate() - period);
  const sinceDate = Number.isFinite(since.getTime()) ? since.toISOString().slice(0, 10) : "";
  const history = prices?.market === market && prices.ticker.toUpperCase() === ticker.toUpperCase()
    ? prices.history.filter((point) => point.currency === currency && point.date <= chartDate && point.date >= sinceDate) : [];

  return <main className="pageShell semiPage marketStockPage">
    <div className="semiBreadcrumb"><Link to={back}>← {back.startsWith("/calendar-history") ? "누적 기록" : sourceLabel}로 돌아가기</Link><span>/</span><span>{stock?.name ?? ticker}</span></div>
    <DataRefreshStatus refreshing={refreshing || pricesLoading} lastCheckedAt={lastCheckedAt} lastSourceAt={lastSourceAt ?? currentQuote?.fetched_at}
      onRefresh={async () => { await refresh(); await reloadPrices(); }} />
    {!contextValid ? <ErrorNotice message="조회할 시장과 거래일이 없습니다. 캘린더에서 종목을 선택해 주세요." /> : null}
    {loading ? <LoadingSpinner /> : null}
    {error ? <div><ErrorNotice message={error} /><button className="semiTextButton" onClick={refresh}>다시 불러오기</button></div> : null}
    {stock ? <>
      <header className="semiDetailHeader"><div><p className="eyebrow">{stock.exchange} / {category}</p><h1>{stock.name}</h1>
        <p>{stock.ticker} · {sourceLabel}</p><div className="marketStockActions"><a href={quote.href} target="_blank" rel="noreferrer">{quote.label} 외부 시세 ↗</a>
          {symbol ? <a href={tradingViewUrl(symbol)} target="_blank" rel="noreferrer">TradingView에서 보기 ↗</a> : null}</div></div>
        <div className="semiQuoteHero"><span>{currentQuote ? "현재가 · 원본 직접 조회" : "캘린더 기록 종가"}</span><strong>{priceLabel(price, currency)}</strong>
          <b className={((currentQuote?.change_pct ?? stock.change_pct) ?? 0) >= 0 ? "semiUp" : "semiDown"}>{formatPercent(currentQuote?.change_pct ?? stock.change_pct)}</b>
          <small>{currentQuote ? `${currentQuote.source} · ${currentQuote.provider_time?.replace("T", " ") ?? "기준 시각 미제공"}` : `${date} 거래일 기준`}</small></div>
      </header>
      <section className="semiPanel marketStockSnapshot"><div className="semiPanelHeading"><h2>종목 기본 정보</h2><p>선택한 거래일에 저장된 캘린더 기록입니다. 외부 일봉 차트·실적은 제공처의 최신 자료를 표시합니다.</p></div>
        <dl><div><dt>거래소</dt><dd>{stock.exchange}</dd></div><div><dt>업종</dt><dd>{category || "미등록"}</dd></div>
          <div><dt>통화</dt><dd>{currency}</dd></div><div><dt>{"market_cap_fetched_at" in stock ? "시가총액 · 수집 시점 기준" : "기록된 시가총액"}</dt><dd>{formatMarketCap({ ...stock, market_cap_currency: stock.market_cap_currency ?? currency })}</dd></div>
          {"turnover" in stock ? <><div><dt>거래대금 순위</dt><dd>{stock.rank}위</dd></div><div><dt>당일 거래대금</dt><dd>{formatHistoryMoney({ [stock.turnover_currency ?? currency]: stock.turnover })}</dd></div></> : null}
          {"high_type" in stock ? <div><dt>신고가 유형</dt><dd>{stock.high_type === "all_time" ? "역대 신고가" : "52주 신고가"}</dd></div> : null}
          <div><dt>기록일</dt><dd>{date}</dd></div></dl>
        {currentQuote ? <p className="semiFootnote">선택한 날의 기록 종가: {priceLabel(recordedPrice, stock.currency ?? currency)} · 상단 현재가와 구분됩니다.</p> : null}
        <PeriodReturns values={stock.period_returns} />
        {"description" in stock && stock.description ? <p className="marketStockDescription">{stock.description}</p> : null}
      </section>
      <section className="semiPanel marketStockChart"><div className="semiPanelHeading semiHeadingSplit"><div><h2>{sourceDetail?.history ? "주가 차트 · 원본 조회" : "캘린더 가격 기록"}</h2>
        <p>{sourceDetail?.history ? "Yahoo Finance 일별 종가 · 새로고침으로 원본에서 갱신" : "캘린더에 등장한 거래일의 종가 · 전체 거래일의 연속 일봉과 다릅니다."}</p></div>
        <div className="semiPeriodTabs" aria-label="가격 기록 조회 기간">{PERIODS.map((days) => <button key={days} className={days === period ? "active" : ""} onClick={() => setPeriod(days)}>{days}일</button>)}</div></div>
        {pricesLoading ? <LoadingSpinner /> : null}
        {pricesError ? <><ErrorNotice message={pricesError} /><button className="semiTextButton" onClick={refreshPrices}>가격 기록 다시 불러오기</button></> : null}
        <SemiconductorLineChart points={history.map((point) => ({ date: point.date, value: point.close }))} title={`${stock.name} 캘린더 종가`} unit={currency === "KRW" ? "원" : currency} />
        <p className="semiFootnote">{history.length}개 거래일의 기록 · {chartDate}까지 · 분할·배당을 조정하지 않은 당시 종가입니다.</p>
        <div className="semiTableWrap"><table className="semiTable"><thead><tr><th>기록일</th><th>종가</th></tr></thead><tbody>
          {[...history].reverse().slice(0, 20).map((point) => <tr key={point.date}><td>{point.date}</td><td className="semiNumber">{priceLabel(point.close, point.currency)}</td></tr>)}
        </tbody></table></div>
        {symbol ? <><button className="semiTextButton marketFullChartButton" aria-expanded={showFullChart} onClick={() => setShowFullChart((value) => !value)}>{showFullChart ? "전체 일봉 차트 접기" : "TradingView 전체 일봉 차트 보기"}</button>
          {showFullChart ? <><p className="semiFootnote">제공처가 외부 표시를 지원하는 종목에 한해 표시됩니다.</p><TradingViewWidget key={currentQuote?.fetched_at} symbol={symbol} kind="chart" /></> : null}</> : null}
      </section>
      <section className="semiPanel marketStockFinancials"><div className="semiPanelHeading"><h2>실적 · 투자 지표</h2><p>매출·이익·재무비율 등 제공처가 지원하는 기업 정보입니다. 자료가 없는 종목은 원문에서 확인해 주세요.</p>
        <a className="semiTextButton" href={stock.exchange === "KOSPI" || stock.exchange === "KOSDAQ"
          ? `https://m.stock.naver.com/domestic/stock/${stock.ticker.split(".")[0]}/total` : symbol ? `${tradingViewUrl(symbol)}financials-overview/` : quote.href}
          target="_blank" rel="noreferrer">실적 원문 보기 ↗</a></div>
        {sourceDetail?.annual_financials || sourceDetail?.quarterly_financials ? <>
          <p className="semiFootnote">Naver Finance 확정 실적 · 단위: 억원 · 원본 직접 조회</p><RecentFinancialSummary summary={sourceDetail.recent_financials} />
          <div className="semiFinanceGrid"><FinancialTable title="연간" rows={sourceDetail.annual_financials ?? []} /><FinancialTable title="분기" rows={sourceDetail.quarterly_financials ?? []} /></div>
        </> : symbol ? <TradingViewWidget key={currentQuote?.fetched_at} symbol={symbol} kind="financials" /> : <p className="semiEmpty">이 거래소의 내장 재무 자료는 지원하지 않습니다. 위의 외부 시세 링크에서 확인해 주세요.</p>}
      </section>
      <p className="semiFootnote">기본 정보의 가격·등락률은 {date} 캘린더에 저장된 값입니다. 외부 전체 일봉 차트와 실적은 TradingView 제공 자료로 기준일과 통화가 다를 수 있으며,
        종목·거래소에 따라 일부 자료가 제공되지 않을 수 있습니다. <a href={quote.href} target="_blank" rel="noreferrer">{quote.label}에서 종목 확인 ↗</a></p>
    </> : null}
  </main>;
}
