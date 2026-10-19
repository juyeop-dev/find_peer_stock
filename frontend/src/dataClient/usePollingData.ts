import { useCallback, useEffect, useRef, useState } from "react";

const POLL_INTERVAL_MS = 60_000;
export type DataLoader<T> = (signal: AbortSignal, fromSource?: boolean, current?: T | null) => Promise<T>;

export function usePollingData<T>(loadData: DataLoader<T> | null, pollIntervalMs = POLL_INTERVAL_MS) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(Boolean(loadData));
  const [refreshing, setRefreshing] = useState(false);
  const [lastCheckedAt, setLastCheckedAt] = useState<string | null>(null);
  const [lastSourceAt, setLastSourceAt] = useState<string | null>(null);
  const dataRef = useRef<T | null>(null);
  const refreshRef = useRef<(fromSource: boolean) => Promise<void>>(async () => {});

  useEffect(() => {
    let alive = true;
    let inFlight = false;
    let controller: AbortController | undefined;
    let timeoutId: number | undefined;

    setData(null);
    setError(null);
    setLoading(Boolean(loadData));
    setRefreshing(false);
    setLastCheckedAt(null);
    setLastSourceAt(null);
    dataRef.current = null;

    const clearPoll = () => {
      window.clearTimeout(timeoutId);
      timeoutId = undefined;
    };

    async function poll(fromSource = false) {
      if (!alive || !loadData || inFlight) return;
      clearPoll();
      inFlight = true;
      controller = new AbortController();
      setRefreshing(true);
      try {
        const payload = await loadData(controller.signal, fromSource, dataRef.current);
        if (!alive) return;
        // Replace the whole response so peer prices and status changes also appear.
        setData(payload);
        dataRef.current = payload;
        const metadata = payload as { source_fetched_at?: string; refresh_warning?: string } | null;
        setError(metadata?.refresh_warning ?? null);
        if (metadata?.source_fetched_at) setLastSourceAt(metadata.source_fetched_at);
        setLastCheckedAt(new Date().toISOString());
      } catch (exc: unknown) {
        if (alive) {
          setError(exc instanceof Error ? exc.message : "데이터를 불러오지 못했습니다.");
        }
      } finally {
        inFlight = false;
        if (alive) {
          setLoading(false);
          setRefreshing(false);
          if (document.visibilityState === "visible") {
            timeoutId = window.setTimeout(() => void poll(), pollIntervalMs);
          }
        }
      }
    }

    const refresh = (fromSource = false) => poll(fromSource);
    const refreshWhenVisible = () => {
      if (document.visibilityState === "visible") void refresh();
      else clearPoll();
    };
    refreshRef.current = refresh;
    void refresh();
    document.addEventListener("visibilitychange", refreshWhenVisible);
    window.addEventListener("focus", refreshWhenVisible);
    window.addEventListener("online", refreshWhenVisible);

    return () => {
      alive = false;
      clearPoll();
      controller?.abort();
      document.removeEventListener("visibilitychange", refreshWhenVisible);
      window.removeEventListener("focus", refreshWhenVisible);
      window.removeEventListener("online", refreshWhenVisible);
    };
  }, [loadData, pollIntervalMs]);

  const refresh = useCallback(() => refreshRef.current(true), []);
  const reload = useCallback(() => refreshRef.current(false), []);
  return { data, error, loading, refreshing, lastCheckedAt, lastSourceAt, refresh, reload };
}
