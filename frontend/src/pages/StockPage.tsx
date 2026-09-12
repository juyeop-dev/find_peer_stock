import { useCallback } from "react";
import { useParams } from "react-router-dom";
import { ErrorNotice } from "../components/ErrorNotice";
import { LoadingSpinner } from "../components/LoadingSpinner";
import { PeerGroupSection } from "../components/PeerGroupSection";
import { QuoteSummary } from "../components/QuoteSummary";
import { StockHeader } from "../components/StockHeader";
import { getStockSummary } from "../dataClient/staticStockDataClient";
import { usePollingData } from "../dataClient/usePollingData";
import { DataRefreshStatus } from "../components/DataRefreshStatus";

export function StockPage() {
  const params = useParams();
  const ticker = params.ticker ? decodeURIComponent(params.ticker) : "";
  const loadSummary = useCallback((signal: AbortSignal) => getStockSummary(ticker, signal), [ticker]);
  const { data: summary, error, loading, refreshing, lastCheckedAt, refresh } = usePollingData(ticker ? loadSummary : null);

  return (
    <main className="pageShell">
      {loading ? <LoadingSpinner /> : null}
      {error ? <ErrorNotice message={error} /> : null}
      {!ticker ? <ErrorNotice message="티커가 없습니다." /> : null}

      <DataRefreshStatus refreshing={refreshing} lastCheckedAt={lastCheckedAt}
        generatedAt={summary?.generated_at} onRefresh={refresh} />

      {summary ? (
        <>
          <StockHeader company={summary.company} />
          <QuoteSummary
            generatedAt={summary.generated_at}
            quote={summary.quote}
          />

          <section className="companyInfo">
            <div>
              <span className="eyebrow">기업 정보</span>
              <p>{summary.company.market_note || summary.company.theme || "등록된 설명이 없습니다."}</p>
            </div>
            <dl>
              <div>
                <dt>시가총액</dt>
                <dd>준비 중</dd>
              </div>
              <div>
                <dt>순위</dt>
                <dd>준비 중</dd>
              </div>
            </dl>
          </section>

          <div className="peerStack">
            {summary.peer_groups.length > 0 ? (
              summary.peer_groups.map((group) => (
                <PeerGroupSection
                  key={`${group.group.name}-${group.group.summary ?? ""}`}
                  group={group}
                />
              ))
            ) : (
              <section className="emptyPeer">
                <h2>Peer 기업</h2>
                <p>등록된 peer 그룹이 없습니다.</p>
              </section>
            )}
          </div>
        </>
      ) : null}
    </main>
  );
}
