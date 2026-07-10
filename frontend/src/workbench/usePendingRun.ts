// frontend/src/workbench/usePendingRun.ts
//
// v1.6.9 B1 — the shared "index-wait" layer, generalized VERBATIM from the
// v1.6.8 genesis polling machine that used to live inline in
// WorkbenchRouteContainer.tsx.
//
// A newly executed run (genesis today; draft-execute in a later task) produces
// a run id immediately, but the lineage forest index catches up
// asynchronously. This hook bridges that gap: it polls /runs for the produced
// run and hands control back to the caller when
//   - the run appears in the forest index   → onIndexed(runId)
//   - the run reaches a terminal failure     → onFailed(draftId)
//   - the retry budget is exhausted          → warn + clear pending
//
// Budget semantics (unchanged from the container): the retry limit only bounds
// the gap between the run reaching a TERMINAL state and the forest index
// catching up. While /runs still reports the run running, we poll WITHOUT
// burning attempts — otherwise a slow run (e.g. honest-DID, minutes long) would
// exhaust the budget in ~15s and silently strand the draft on the canvas. So
// 30 × 1s = a 30s indexing budget AFTER the run finishes, independent of how
// long the run itself takes.
//
// The pending state lives in the CALLER (like the original genesis state); the
// hook only reads it and requests updates via setPending.
//
// Callback stability: onIndexed/onFailed/refetch/setPending are latest-ref'd
// INSIDE the hook, so callers may pass plain inline arrows safely. The polling
// effect re-runs ONLY when forest/pending/projectRoot change — matching the
// original inline effect's deps — so fresh callback instances on every render
// neither restart the 1000ms timer (which would starve the poll under fast
// re-renders) nor go stale (the effect body calls through refs updated each
// render).

import { useEffect, useRef } from "react";
import { fetchRunDetail } from "../api";

const PENDING_RUN_RETRY_LIMIT = 30;
const PENDING_RUN_RETRY_DELAY_MS = 1000;

export interface PendingRun {
  runId: string;
  draftId: string;
  attempts: number;
}

interface ForestLike {
  heads: { runId: string }[];
}

export function usePendingRun({
  pending,
  projectRoot,
  forest,
  refetch,
  onIndexed,
  onFailed,
  setPending,
}: {
  pending: PendingRun | null;
  projectRoot: string;
  forest: ForestLike | null;
  refetch: () => void;
  onIndexed: (runId: string) => void;
  onFailed: (draftId: string) => void;
  setPending: (
    updater: (current: PendingRun | null) => PendingRun | null,
  ) => void;
}): void {
  // Latest-ref the callbacks so the effect depends only on forest/pending/
  // projectRoot (the original inline effect's semantics; refetch there was
  // useCallback-stable). Without this, inline-arrow callers would tear down
  // and restart the poll timer on every render.
  const refetchRef = useRef(refetch);
  refetchRef.current = refetch;
  const onIndexedRef = useRef(onIndexed);
  onIndexedRef.current = onIndexed;
  const onFailedRef = useRef(onFailed);
  onFailedRef.current = onFailed;
  const setPendingRef = useRef(setPending);
  setPendingRef.current = setPending;

  useEffect(() => {
    if (!pending || !forest) return undefined;
    const { runId, draftId, attempts } = pending;
    if (forest.heads.some((h) => h.runId === runId)) {
      onIndexedRef.current(runId);
      return undefined;
    }
    // The retry budget only covers the gap between the run reaching a terminal
    // state and the forest index catching up. A run itself can take minutes
    // (e.g. honest-DID), so while /runs still reports it running we poll
    // without burning attempts — otherwise every slow run used to exhaust the
    // budget in 15s and silently strand the draft on the canvas.
    if (attempts >= PENDING_RUN_RETRY_LIMIT) {
      console.warn(
        `run ${runId} reached a terminal state but never appeared in the forest index; giving up polling`,
      );
      setPendingRef.current(() => null);
      return undefined;
    }
    let cancelled = false;
    const timer = window.setTimeout(async () => {
      let burnAttempt = true;
      try {
        const detail = await fetchRunDetail(projectRoot, runId);
        if (cancelled) return;
        if (detail.status === "failed" || detail.status === "blocked") {
          // Terminal failure: the run will never be indexed. Surface it on the
          // draft node instead of polling forever / vanishing silently.
          onFailedRef.current(draftId);
          setPendingRef.current(() => null);
          return;
        }
        burnAttempt = detail.status !== "running";
      } catch {
        /* transient status-poll failure — spend an attempt and retry */
      }
      if (cancelled) return;
      setPendingRef.current((current) =>
        current === null || current.runId !== runId
          ? current
          : {
              ...current,
              attempts: burnAttempt ? current.attempts + 1 : current.attempts,
            },
      );
      refetchRef.current();
    }, PENDING_RUN_RETRY_DELAY_MS);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [forest, pending, projectRoot]);
}
