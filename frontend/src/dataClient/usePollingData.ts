import { useCallback, useEffect, useRef, useState } from "react";

const POLL_INTERVAL_MS = 60_000;
type DataLoader<T> = (signal: AbortSignal) => Promise<T>;

export function usePollingData<T>(loadData: DataLoader<T> | null) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(Boolean(loadData));
  const [refreshing, setRefreshing] = useState(false);
  const [lastCheckedAt, setLastCheckedAt] = useState<string | null>(null);
  const refreshRef = useRef<() => void>(() => {});

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

    const clearPoll = () => {
      window.clearTimeout(timeoutId);
      timeoutId = undefined;
    };

    async function poll() {
      if (!alive || !loadData || inFlight) return;
      clearPoll();
      inFlight = true;
      controller = new AbortController();
      setRefreshing(true);
      try {
        const payload = await loadData(controller.signal);
        if (!alive) return;
        // Replace the whole response so peer prices and status changes also appear.
        setData(payload);
        setError(null);
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
            timeoutId = window.setTimeout(() => void poll(), POLL_INTERVAL_MS);
          }
        }
      }
    }

    const refresh = () => { void poll(); };
    const refreshWhenVisible = () => {
      if (document.visibilityState === "visible") refresh();
      else clearPoll();
    };
    refreshRef.current = refresh;
    refresh();
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
  }, [loadData]);

  const refresh = useCallback(() => refreshRef.current(), []);
  return { data, error, loading, refreshing, lastCheckedAt, refresh };
}
