// frontend/src/lineage/LineageRouteContainer.tsx
//
// V1.5.0 lineage route shell (Step 5, T5.4).
//
// Reads projectRoot + runId from props, drives the data + URL hooks, and
// renders exactly one of: <Loading />, <ErrorBanner />, or the workbench
// inside <LineageContext.Provider>. Per plan §8 T5.4 DoD: file < 80 LOC,
// no imports from lineage/graph/* or lineage/detail/*.
//
// The success-branch body is currently a placeholder (<WorkbenchSlot />)
// because GraphWorkbench arrives in T5.6. T5.7 then flips runDetail.tsx
// from LineageTab to this container.

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
      <WorkbenchSlot />
    </LineageContext.Provider>
  );
}

/**
 * Placeholder until T5.6 introduces GraphWorkbench. Renders a minimal
 * confirmation so the success branch is reachable in tests.
 */
function WorkbenchSlot() {
  return (
    <div
      className="lineage-root"
      style={{ padding: 24 }}
      data-testid="workbench-slot"
    >
      Lineage loaded.
    </div>
  );
}
