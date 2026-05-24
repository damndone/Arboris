// frontend/src/lineage/LineageRouteContainer.tsx
//
// V1.5.0 lineage route shell (Step 5, T5.4 + T5.6).
//
// Reads projectRoot + runId from props, drives the data + URL hooks, and
// renders exactly one of: <Loading />, <ErrorBanner />, or
// <GraphWorkbench /> inside <LineageContext.Provider>. T5.7 flips
// runDetail.tsx from LineageTab to this container.

import { GraphWorkbench } from "./GraphWorkbench";
import { useGraphData } from "./hooks/useGraphData";
import { useSelectedNode } from "./hooks/useSelectedNode";
import { LineageContext } from "./LineageContext";
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
  const { selectedKey, select } = useSelectedNode();

  if (loading) return <Loading />;
  if (error !== null) return <ErrorBanner error={error} onRetry={refetch} />;
  if (model === null) return <Loading />; // defensive — should not happen

  return (
    <LineageContext.Provider value={{ model, selectedKey, select }}>
      <GraphWorkbench />
    </LineageContext.Provider>
  );
}
