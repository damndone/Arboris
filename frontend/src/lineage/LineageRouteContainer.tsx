// frontend/src/lineage/LineageRouteContainer.tsx
//
// V1.5.0 lineage route shell (Step 5, T5.4 + T5.6).
//
// Reads projectRoot + runId from props, drives the data + URL hooks, and
// renders exactly one of: <Loading />, <ErrorBanner />, or
// <GraphWorkbench /> inside <LineageContext.Provider>. T5.7 flips
// runDetail.tsx from LineageTab to this container.

import { useMemo } from "react";
import { GraphWorkbench } from "./GraphWorkbench";
import { useGraphData } from "./hooks/useGraphData";
import { useSelectedNode } from "./hooks/useSelectedNode";
import { LineageContext, type LineageContextValue } from "./LineageContext";
import { ErrorBanner, Loading } from "./statusViews";
import "./tokens/lineage.css";

interface LineageRouteContainerProps {
  projectRoot: string;
  runId: string;
}

export function LineageRouteContainer({
  projectRoot,
  runId,
}: LineageRouteContainerProps) {
  const { model, loading, error, refetch } = useGraphData(projectRoot, runId);
  const { selectedKey, select } = useSelectedNode(
    model?.nodes ?? null,
    model?.runId ?? null,
  );

  // Stabilise the context value across renders so consumers (DetailDrawer,
  // future panels) only re-render when one of model / selectedKey / select
  // actually changes — not on every container render.
  // [REV-3 #7 — Step 5 adversarial review]
  const ctx = useMemo<LineageContextValue | null>(
    () => (model === null ? null : { model, selectedKey, select }),
    [model, selectedKey, select],
  );

  if (loading) return <Loading />;
  if (error !== null) return <ErrorBanner error={error} onRetry={refetch} />;
  // Defensive: shouldn't happen — useGraphData guarantees one of
  // {loading, error, model} is set. Kept as a typesafety guard so the
  // Provider never receives null.
  if (ctx === null) return <Loading />;

  return (
    <LineageContext.Provider value={ctx}>
      <GraphWorkbench />
    </LineageContext.Provider>
  );
}
