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
// hook only reads it and requests updates via setPending. onIndexed/onFailed
// callbacks are re-created each render — pass plain inline arrows; do NOT
// memoize them in a way that captures a stale pending value.

import { useEffect } from "react";
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
  useEffect(() => {
    if (!pending || !forest) return undefined;
    const { runId, draftId, attempts } = pending;
    if (forest.heads.some((h) => h.runId === runId)) {
      onIndexed(runId);
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
      setPending(() => null);
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
          onFailed(draftId);
          setPending(() => null);
          return;
        }
        burnAttempt = detail.status !== "running";
      } catch {
        /* transient status-poll failure — spend an attempt and retry */
      }
      if (cancelled) return;
      setPending((current) =>
        current === null || current.runId !== runId
          ? current
          : {
              ...current,
              attempts: burnAttempt ? current.attempts + 1 : current.attempts,
            },
      );
      refetch();
    }, PENDING_RUN_RETRY_DELAY_MS);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [forest, pending, projectRoot, refetch, onIndexed, onFailed, setPending]);
}
