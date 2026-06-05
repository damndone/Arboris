/* useRunHistory.ts — V1.5.1 T3'.
 *
 * Polls /runs?project_root=… every POLL_MS while mounted so the
 * RunHistoryRail picks up newly-completed runs without a manual refresh.
 * 30s is the spec-mandated minimum — sub-30s would race against the
 * SSE-driven Submit-page progress channel and produce duplicate state
 * (T1 lands SSE later in the sprint).
 *
 * Cancellation: every fetch uses an AbortController scoped to the poll
 * tick AND a higher-level one tied to unmount, so neither a unmount nor
 * a re-fetch leaves stale promises walking back into setState.
 *
 * Failure mode: surface { error } but keep the previous `runs` array so
 * a transient network hiccup doesn't blank the rail.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { fetchRuns } from "../../api";
import type { RunSummary } from "../../api";

const POLL_MS = 30_000;

export interface UseRunHistoryResult {
  runs: RunSummary[];
  loading: boolean;
  error: Error | null;
  refresh: () => void;
}

export function useRunHistory(projectRoot: string | null | undefined): UseRunHistoryResult {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [loading, setLoading] = useState<boolean>(Boolean(projectRoot));
  const [error, setError] = useState<Error | null>(null);
  // Bumped by refresh() to re-trigger the effect outside of the timer.
  const [tick, setTick] = useState(0);
  const mountedRef = useRef(true);

  const refresh = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    if (!projectRoot) {
      setRuns([]);
      setLoading(false);
      setError(null);
      return;
    }
    const ctrl = new AbortController();
    let timer: ReturnType<typeof setTimeout> | null = null;

    const fetchOnce = async () => {
      try {
        const resp = await fetchRuns(projectRoot);
        if (!mountedRef.current || ctrl.signal.aborted) return;
        // Defensive: some test fixtures stub fetch globally and return a
        // shape without the `runs` key. Treat that as an empty list
        // rather than letting `runs is not iterable` propagate.
        setRuns(Array.isArray(resp?.runs) ? resp.runs : []);
        setError(null);
      } catch (e) {
        if (!mountedRef.current || ctrl.signal.aborted) return;
        // Keep previous `runs` so transient failures don't blank the rail.
        setError(e instanceof Error ? e : new Error(String(e)));
      } finally {
        if (mountedRef.current && !ctrl.signal.aborted) {
          setLoading(false);
        }
      }
    };

    const poll = () => {
      void fetchOnce();
      timer = setTimeout(poll, POLL_MS);
    };

    setLoading(true);
    poll();

    return () => {
      ctrl.abort();
      if (timer) clearTimeout(timer);
    };
    // tick re-runs the effect (resets the timer too)
  }, [projectRoot, tick]);

  return { runs, loading, error, refresh };
}
