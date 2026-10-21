import { useCallback, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { ErrorNotice } from "../components/ErrorNotice";
import { LoadingSpinner } from "../components/LoadingSpinner";
import { PeriodReturns } from "../components/PeriodReturns";
import { TradingViewWidget } from "../components/TradingViewWidget";
import { StockHistoryChart } from "../components/StockHistoryChart";
import { getNewHighReport, getTurnoverReport } from "../dataClient/staticStockDataClient";
import { usePollingData } from "../dataClient/usePollingData";
import { calendarReturnLink, tradingViewSymbol, tradingViewUrl } from "../dataClient/stockDetailLinks";
import { getExternalQuoteLink } from "../dataClient/externalLinks";
import { formatMarketCap } from "../dataClient/formatters";
import { formatHistoryMoney } from "../dataClient/calendarHistory";
import { formatPercent } from "../dataClient/semiconductorMath";
import "../styles/marketStock.css";
import { DataRefreshStatus } from "../components/DataRefreshStatus";
import { StockInformationPanel } from "../components/StockInformationPanel";
import { getStockInformation } from "../dataClient/stockInformationClient";
import { liveDetailFor, liveQuoteFor, refreshDetails } from "../dataClient/liveStockDataClient";
import { getSectorStock } from "../dataClient/sectorDataClient";

const MARKET_CURRENCIES: Record<string, string> = { korea: "KRW", us: "USD", japan: "JPY", taiwan: "TWD", china: "CNY", europe: "EUR" };

function validDate(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const parsed = new Date(`${value}T00:00:00Z`);
  return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
}

function priceLabel(price: number | null | undefined, currency: string): string {
  return price == null ? "미등록" : `${new Intl.NumberFormat("ko-KR", { maximumFractionDigits: currency === "KRW" || currency === "JPY" ? 0 : Math.abs(price) < 0.01 ? 8 : Math.abs(price) < 1 ? 4 : 2 }).format(price)} ${currency}`;
}

export function MarketStockPage() {
  const { ticker = "" } = useParams();
  const [params] = useSearchParams();
  const [showFullChart, setShowFullChart] = useState(false);
  const source = params.get("source") === "sectors" ? "sectors" : params.get("source") === "turnover" ? "turnover" : "new-highs";
  const market = params.get("market") ?? "";
  const date = params.get("date") ?? "";
  const contextValid = validDate(date) && Object.hasOwn(MARKET_CURRENCIES, market) && (source !== "sectors" || market === "korea");
  const fallback = `/${source}?${new URLSearchParams({ market, date })}`;
  const back = calendarReturnLink(params.get("returnTo"), contextValid ? fallback : `/${source}`);
  const sourceLabel = source === "sectors" ? "섹터 상승률" : source === "new-highs" ? "신고가 캘린더" : "거래대금 캘린더";
  const loadStock = useCallback(async (signal: AbortSignal, fromSource = false) => {
    const report = source === "sectors" ? { market: "korea", date, entries: [await getSectorStock(ticker, signal, date)] } : source === "new-highs" ? await getNewHighReport(market, date, signal) : await getTurnoverReport(market, date, signal);
    if (report.market !== market || report.date !== date) throw new Error("선택한 날짜의 기록과 일치하지 않습니다.");
    const stock = report.entries.find((item) => item.ticker.toUpperCase() === ticker.toUpperCase());
    if (!stock) throw new Error("선택한 목록에서 이 종목을 찾을 수 없습니다.");
    const metadata = fromSource ? await refreshDetails([{ ticker, exchange: stock.exchange }], signal) : {};
    const information = await getStockInformation(ticker, stock.exchange, signal, fromSource).catch(error => {
      if (signal.aborted) throw error;
      if (fromSource) Object.assign(metadata, {refresh_warning: "일부 기업 정보·실적 조회에 실패해 이전 자료를 유지합니다."});
      return undefined;
    });
    return { stock, source, market, date, information, ...metadata };
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
  const recordDate = stock && "date" in stock ? stock.date : date;

  return <main className="pageShell semiPage marketStockPage">
    <div className="semiBreadcrumb"><Link to={back}>← {back.startsWith("/calendar-history") ? "누적 기록" : sourceLabel}로 돌아가기</Link><span>/</span><span>{stock?.name ?? ticker}</span></div>
    <DataRefreshStatus refreshing={refreshing} lastCheckedAt={lastCheckedAt} lastSourceAt={lastSourceAt ?? currentQuote?.fetched_at} onRefresh={refresh} />
    {!contextValid ? <ErrorNotice message="조회할 시장과 거래일이 없습니다. 캘린더에서 종목을 선택해 주세요." /> : null}
    {loading ? <LoadingSpinner /> : null}
    {error ? <div><ErrorNotice message={error} /><button className="semiTextButton" onClick={refresh}>다시 불러오기</button></div> : null}
    {stock ? <>
      <header className="semiDetailHeader"><div><p className="eyebrow">{stock.exchange} / {category}</p><h1>{stock.name}</h1>
        <p>{stock.ticker} · {sourceLabel}</p><div className="marketStockActions"><a href={quote.href} target="_blank" rel="noreferrer">{quote.label} 외부 시세 ↗</a>
          {symbol ? <a href={tradingViewUrl(symbol)} target="_blank" rel="noreferrer">TradingView에서 보기 ↗</a> : null}</div></div>
        <div className="semiQuoteHero"><span>{currentQuote ? "현재가 / 최근 제공 가격" : source === "sectors" ? "섹터 조회 가격" : "캘린더 기록 종가"}</span><strong>{priceLabel(price, currency)}</strong>
          <b className={((currentQuote?.change_pct ?? stock.change_pct) ?? 0) >= 0 ? "semiUp" : "semiDown"}>{formatPercent(currentQuote?.change_pct ?? stock.change_pct)}</b>
          <small>{currentQuote ? `${currentQuote.source} · ${currentQuote.provider_time?.replace("T", " ") ?? "기준 시각 미제공"}` : `${recordDate} 거래일 기준`}</small></div>
      </header>
      <section className="semiPanel marketStockSnapshot"><div className="semiPanelHeading"><h2>종목 기본 정보</h2><p>{source === "sectors" ? "선택한 거래일의 섹터 목록에 저장된 종목 정보입니다." : "선택한 거래일에 저장된 캘린더 기록입니다."} 외부 일봉 차트·실적은 제공처의 최신 자료를 표시합니다.</p></div>
        <dl><div><dt>거래소</dt><dd>{stock.exchange}</dd></div><div><dt>업종</dt><dd>{category || "미등록"}</dd></div>
          <div><dt>통화</dt><dd>{currency}</dd></div><div><dt>{"market_cap_fetched_at" in stock ? "시가총액 · 수집 시점 기준" : "기록된 시가총액"}</dt><dd>{formatMarketCap({ ...stock, market_cap_currency: stock.market_cap_currency ?? currency })}</dd></div>
          {"rank" in stock ? <div><dt>거래대금 순위</dt><dd>{stock.rank}위</dd></div> : null}
          {"turnover" in stock ? <div><dt>당일 거래대금</dt><dd>{stock.turnover === null ? "미제공" : formatHistoryMoney({ [stock.turnover_currency ?? currency]: stock.turnover })}</dd></div> : null}
          {"high_type" in stock ? <div><dt>신고가 유형</dt><dd>{stock.high_type === "all_time" ? "역대 신고가" : "52주 신고가"}</dd></div> : null}
          <div><dt>기록일</dt><dd>{recordDate}</dd></div></dl>
        {currentQuote ? <p className="semiFootnote">선택한 날의 기록 종가: {priceLabel(recordedPrice, stock.currency ?? currency)} · 상단 현재가와 구분됩니다.</p> : null}
        <PeriodReturns values={"period_returns" in stock ? stock.period_returns : undefined} />
        {"description" in stock && stock.description ? <p className="marketStockDescription">{stock.description}</p> : null}
      </section>
      <div className="marketStockChart"><StockHistoryChart ticker={stock.ticker} name={stock.name} exchange={stock.exchange} currency={currency} refreshKey={sourceDetail?.fetched_at} />
        {symbol ? <><button className="semiTextButton marketFullChartButton" aria-expanded={showFullChart} onClick={() => setShowFullChart((value) => !value)}>{showFullChart ? "전체 일봉 차트 접기" : "TradingView 전체 일봉 차트 보기"}</button>
          {showFullChart ? <><p className="semiFootnote">제공처가 외부 표시를 지원하는 종목에 한해 표시됩니다.</p><TradingViewWidget key={currentQuote?.fetched_at} symbol={symbol} kind="chart" /></> : null}</> : null}
      </div>
      <div className="marketStockFinancials"><StockInformationPanel ticker={ticker} exchange={stock.exchange} refreshKey={data?.information?.financials_fetched_at ?? sourceDetail?.fetched_at} /><div className="semiPanelHeading">
        <a className="semiTextButton" href={stock.exchange === "KOSPI" || stock.exchange === "KOSDAQ"
          ? `https://m.stock.naver.com/domestic/stock/${stock.ticker.split(".")[0]}/total` : symbol ? `${tradingViewUrl(symbol)}financials-overview/` : quote.href}
          target="_blank" rel="noreferrer">실적 원문 보기 ↗</a></div>
        {symbol ? <details><summary>TradingView 실적 원문 화면</summary><TradingViewWidget key={currentQuote?.fetched_at} symbol={symbol} kind="financials" /></details> : null}
      </div>
      <p className="semiFootnote">{source === "sectors" ? `섹터 목록 가격의 거래일은 ${recordDate}입니다.` : `캘린더의 ${date} 당시 가격은 과거 기록입니다.`} 상단에 현재가가 표시되면 원본의 최근 제공 가격이며, 실적은 각 행의 회계기간·통화 기준입니다. 외부 차트와 실적은 제공처 자료로 기준일과 통화가 다를 수 있으며,
        종목·거래소에 따라 일부 자료가 제공되지 않을 수 있습니다. <a href={quote.href} target="_blank" rel="noreferrer">{quote.label}에서 종목 확인 ↗</a></p>
    </> : null}
  </main>;
}
