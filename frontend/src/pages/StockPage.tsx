import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { ErrorNotice } from "../components/ErrorNotice";
import { LoadingSpinner } from "../components/LoadingSpinner";
import { PeerGroupSection } from "../components/PeerGroupSection";
import { QuoteSummary } from "../components/QuoteSummary";
import { StockHeader } from "../components/StockHeader";
import { getStockSummary } from "../dataClient/staticStockDataClient";
import type { StockSummary } from "../dataClient/types";

const STOCK_POLL_INTERVAL_MS = 60_000;

export function StockPage() {
  const params = useParams();
  const ticker = params.ticker ? decodeURIComponent(params.ticker) : "";
  const [summary, setSummary] = useState<StockSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [lastAutoCheckedAt, setLastAutoCheckedAt] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setSummary(null);
    setLastAutoCheckedAt(null);

    if (!ticker) {
      setError("티커가 없습니다.");
      setLoading(false);
      return () => {
        alive = false;
      };
    }

    getStockSummary(ticker, false)
      .then((payload) => {
        if (alive) {
          setSummary(payload);
          setLastAutoCheckedAt(new Date().toISOString());
          setError(null);
        }
      })
      .catch((exc: unknown) => {
        if (alive) {
          setError(exc instanceof Error ? exc.message : "종목 데이터를 불러오지 못했습니다.");
        }
      })
      .finally(() => {
        if (alive) {
          setLoading(false);
        }
      });

    return () => {
      alive = false;
    };
  }, [ticker]);

  useEffect(() => {
    if (!ticker) {
      return;
    }

    let alive = true;

    const poll = async () => {
      try {
        const payload = await getStockSummary(ticker, true);
        if (!alive) {
          return;
        }

        setSummary((current) => {
          if (!current || shouldReplaceSummary(current, payload)) {
            return payload;
          }
          return current;
        });
        setLastAutoCheckedAt(new Date().toISOString());
        setError(null);
      } catch (exc) {
        if (alive) {
          setError(exc instanceof Error ? exc.message : "자동 갱신 데이터를 불러오지 못했습니다.");
        }
      }
    };

    const intervalId = window.setInterval(() => {
      void poll();
    }, STOCK_POLL_INTERVAL_MS);

    return () => {
      alive = false;
      window.clearInterval(intervalId);
    };
  }, [ticker]);

  return (
    <main className="pageShell">
      {loading ? <LoadingSpinner /> : null}
      {error ? <ErrorNotice message={error} /> : null}

      {summary ? (
        <>
          <StockHeader company={summary.company} />
          <QuoteSummary
            generatedAt={summary.generated_at}
            lastAutoCheckedAt={lastAutoCheckedAt}
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

function shouldReplaceSummary(current: StockSummary, next: StockSummary): boolean {
  return (
    current.generated_at !== next.generated_at ||
    current.quote.fetched_at !== next.quote.fetched_at ||
    current.quote.price !== next.quote.price ||
    current.quote.change !== next.quote.change ||
    current.quote.change_pct !== next.quote.change_pct
  );
}
