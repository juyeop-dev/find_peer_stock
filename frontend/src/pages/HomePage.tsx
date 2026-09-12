import { useMemo } from "react";
import { Link } from "react-router-dom";
import { formatDateTime } from "../dataClient/formatters";
import { getSiteIndex } from "../dataClient/staticStockDataClient";
import { usePollingData } from "../dataClient/usePollingData";
import { DataRefreshStatus } from "../components/DataRefreshStatus";
import { ErrorNotice } from "../components/ErrorNotice";
import { LoadingSpinner } from "../components/LoadingSpinner";

export function HomePage() {
  const { data: index, error, loading, refreshing, lastCheckedAt, refresh } = usePollingData(getSiteIndex);

  const featured = useMemo(() => {
    if (!index) {
      return [];
    }
    return index.stocks.filter((stock) => stock.is_target);
  }, [index]);

  return (
    <main className="pageShell">
      <header className="siteHeader">
        <div>
          <p className="eyebrow">Peer Market Dashboard</p>
          <h1>Stock Peer Site</h1>
        </div>
        <div className="generatedBadge">데이터 생성 · {index ? formatDateTime(index.generated_at) : "-"}</div>
      </header>

      <DataRefreshStatus refreshing={refreshing} lastCheckedAt={lastCheckedAt}
        generatedAt={index?.generated_at} onRefresh={refresh} />

      {loading ? <LoadingSpinner /> : null}
      {error ? <ErrorNotice message={error} /> : null}

      {index ? (
        <>
          <section className="marketBoard" aria-label="시장 지수">
            {["코스피", "코스닥", "일본", "대만", "중국", "미국"].map((name) => (
              <article className="indexTile" key={name}>
                <span>{name}</span>
                <strong>준비 중</strong>
              </article>
            ))}
          </section>

          <section className="contentBand">
            <div className="sectionTitle">
              <h2>관심 종목</h2>
              <span>{featured.length}개</span>
            </div>
            <div className="stockGrid">
              {featured.map((stock) => (
                <Link className="stockTile" key={stock.ticker} to={`/stocks/${encodeURIComponent(stock.ticker)}`}>
                  <span className="tickerText">{stock.ticker}</span>
                  <strong>{stock.name_kr}</strong>
                  <p>{stock.theme}</p>
                </Link>
              ))}
            </div>
          </section>
        </>
      ) : null}
    </main>
  );
}
