// frontend/src/lineage/hooks/useGraphData.ts
//
// V1.5.0 graph fetch + adapt hook (Step 5, T5.1).
//
// Encapsulates the fetch/loading/error state extracted from V1.4.1
// `LineageTab.tsx`. Always returns a V1.5.0 `GraphViewModel` — the raw
// `GraphResponse` is adapted before reaching the UI, so containers never
// see the backend schema directly.
//
// Error model (plan §8 T5.1):
//   - 404                              → { kind: "not_found" }
//   - 422                              → { kind: "corrupt" }
//   - genuine fetch rejection / 5xx    → { kind: "network" }
//   - exception thrown in adaptRunGraph → { kind: "adapter_error" }
//   - UnsupportedGraphSchemaError      → { kind: "unsupported_schema", schemaVersion }

import { useCallback, useEffect, useState } from "react";
import { ApiError, getRunGraph } from "../../api";
import {
  UnsupportedGraphSchemaError,
  adaptRunGraph,
} from "../api/graphAdapter";
import type { GraphViewModel } from "../api/graphViewTypes";

export type GraphError =
  | { kind: "not_found"; detail?: string }
  | { kind: "corrupt"; detail?: string }
  | { kind: "network"; detail?: string }
  | { kind: "adapter_error"; detail?: string }
  | { kind: "unsupported_schema"; schemaVersion: number; detail?: string };

export interface UseGraphDataResult {
  model: GraphViewModel | null;
  loading: boolean;
  error: GraphError | null;
  refetch: () => void;
}

export function classifyError(e: unknown): GraphError {
  if (e instanceof UnsupportedGraphSchemaError) {
    return { kind: "unsupported_schema", schemaVersion: e.schemaVersion };
  }
  if (e instanceof ApiError) {
    if (e.status === 404) return { kind: "not_found", detail: e.message };
    if (e.status === 422) return { kind: "corrupt", detail: e.message };
    return { kind: "network", detail: e.message };
  }
  // A genuine fetch rejection is a TypeError whose message mentions "fetch".
  // Anything else reaching here is an exception thrown INSIDE adaptRunGraph
  // (TypeError/RangeError on malformed data) — a real adapter bug, not the
  // network. Mislabeling it "network" hid adapter bugs behind a JS stack.
  if (e instanceof TypeError && /fetch/i.test(e.message)) {
    return { kind: "network", detail: e.message };
  }
  return { kind: "adapter_error", detail: String(e) };
}

export function useGraphData(
  projectRoot: string,
  runId: string,
): UseGraphDataResult {
  const [model, setModel] = useState<GraphViewModel | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<GraphError | null>(null);
  // `tick` lets `refetch` re-trigger the effect without redefining `load`.
  const [tick, setTick] = useState<number>(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setModel(null);

    getRunGraph(projectRoot, runId)
      .then((raw) => adaptRunGraph(raw)) // throws UnsupportedGraphSchemaError → .catch
      .then((m) => {
        if (cancelled) return;
        setModel(m);
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

  return { model, loading, error, refetch };
}
