// frontend/src/lineage/hooks/useForestData.ts
//
// v1.6.1 (2C.6) — fetch + adapt the cross-run head-set forest.
//
// Mirrors useGraphData's load/error/refetch contract but targets
// GET /runs/{id}/graph?view=headset → ForestViewModel. Used by ForestWorkbench
// when the forest gate is on; the legacy useGraphData path is untouched.

import { useCallback, useEffect, useState } from "react";
import { ApiError, getRunGraphHeadSet } from "../../api";
import { adaptHeadSet } from "../api/graphAdapter";
import type { ForestViewModel } from "../api/graphViewTypes";
import type { GraphError } from "./useGraphData";

export interface UseForestDataResult {
  forest: ForestViewModel | null;
  loading: boolean;
  error: GraphError | null;
  refetch: () => void;
}

function classifyError(e: unknown): GraphError {
  if (e instanceof ApiError) {
    if (e.status === 404) return { kind: "not_found", detail: e.message };
    if (e.status === 422) return { kind: "corrupt", detail: e.message };
    return { kind: "network", detail: e.message };
  }
  return { kind: "network", detail: String(e) };
}

export function useForestData(
  projectRoot: string,
  runId: string,
): UseForestDataResult {
  const [forest, setForest] = useState<ForestViewModel | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<GraphError | null>(null);
  const [tick, setTick] = useState<number>(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setForest(null);

    getRunGraphHeadSet(projectRoot, runId)
      .then((raw) => adaptHeadSet(raw))
      .then((f) => {
        if (cancelled) return;
        setForest(f);
        setLoading(false);
      })
      .catch((e) => {
        if (cancelled) return;
        setError(classifyError(e));
        setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [projectRoot, runId, tick]);

  const refetch = useCallback(() => setTick((t) => t + 1), []);

  return { forest, loading, error, refetch };
}
