// frontend/src/lineage/hooks/useForestData.ts
//
// v1.6.1 (2C.6) — fetch + adapt the cross-run head-set forest.
// v1.6.8 T11 — project-keyed: fetches GET /graph?project_root= (union of ALL
// family head-sets; empty containers for zero-run projects) instead of the
// per-run headset endpoint. The body shape is parity with the per-run view
// (Task 6 hard requirement), so adaptHeadSet consumes it unchanged — the
// project-only `families` key is additive and ignored by the adapter.
//
// Mirrors useGraphData's load/error/refetch contract.

import { useCallback, useEffect, useState } from "react";
import { fetchProjectForest } from "../../api";
import { adaptHeadSet } from "../api/graphAdapter";
import type { ForestViewModel } from "../api/graphViewTypes";
import { classifyError, type GraphError } from "./useGraphData";

export interface UseForestDataResult {
  forest: ForestViewModel | null;
  loading: boolean;
  error: GraphError | null;
  refetch: () => void;
}

export function useForestData(projectRoot: string): UseForestDataResult {
  const [forest, setForest] = useState<ForestViewModel | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<GraphError | null>(null);
  const [tick, setTick] = useState<number>(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setForest(null);

    fetchProjectForest(projectRoot)
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
  }, [projectRoot, tick]);

  const refetch = useCallback(() => setTick((t) => t + 1), []);

  return { forest, loading, error, refetch };
}
