// frontend/src/workbench/WorkbenchRouteContainer.tsx
//
// V1.5.2 P3 — run-level workbench shell. Plan §2.
//
// Replaces `lineage/LineageRouteContainer.tsx` as the entry point for
// /runs/:runId. Owns:
//   - data load (useGraphData)
//   - loading / error / data branching
//   - WorkbenchStateProvider mount (cross-view state)
//   - LineageContext.Provider mount (back-compat for GraphView / DetailDrawer
//     / decision panels — those still consume `useLineage()`)
//   - WorkbenchTopbar (view switcher)
//   - WorkbenchMain (view dispatcher)
//
// LineageRouteContainer.tsx is kept around for one version as a thin
// wrapper that delegates here, so any direct consumer (tests, etc.)
// keeps working.

import { useMemo } from "react";
import { useGraphData } from "../lineage/hooks/useGraphData";
import { useSelectedNode } from "../lineage/hooks/useSelectedNode";
import {
  LineageContext,
  type LineageContextValue,
} from "../lineage/LineageContext";
import { ErrorBanner, Loading } from "../lineage/statusViews";
import "../lineage/tokens/lineage.css";
import { WorkbenchStateProvider } from "./WorkbenchStateProvider";
import { WorkbenchTopbar } from "./WorkbenchTopbar";
import { WorkbenchMain } from "./WorkbenchMain";
import { ContextMenu } from "./ContextMenu";
import { BottomPanel } from "./BottomPanel";
import { SearchPalette } from "./SearchPalette";

interface WorkbenchRouteContainerProps {
  projectRoot: string;
  runId: string;
}

export function WorkbenchRouteContainer({
  projectRoot,
  runId,
}: WorkbenchRouteContainerProps) {
  const { model, loading, error, refetch } = useGraphData(projectRoot, runId);
  const {
    selectedKey,
    select,
    tabs,
    activeTabId,
    setActiveTab,
    closeTab,
    lastEvictedTabId,
  } = useSelectedNode(model?.nodes ?? null, model?.runId ?? null);

  // Same memo pattern LineageRouteContainer used so consumers don't
  // re-render on every container render. [REV-3 #7]
  const lineageCtx = useMemo<LineageContextValue | null>(
    () =>
      model === null
        ? null
        : {
            model,
            selectedKey,
            select,
            tabs,
            activeTabId,
            setActiveTab,
            closeTab,
            lastEvictedTabId,
          },
    [
      model,
      selectedKey,
      select,
      tabs,
      activeTabId,
      setActiveTab,
      closeTab,
      lastEvictedTabId,
    ],
  );

  // Build the set of valid node keys for the provider's `focus`
  // validation. Recomputed only when the node list changes.
  const validNodeKeys = useMemo<ReadonlySet<string> | undefined>(() => {
    if (model === null) return undefined;
    return new Set(model.nodes.map((n) => n.nodeKey));
  }, [model]);

  if (loading) return <Loading />;
  if (error !== null) return <ErrorBanner error={error} onRetry={refetch} />;
  // Defensive: useGraphData guarantees one of {loading, error, model}.
  if (lineageCtx === null) return <Loading />;

  return (
    <WorkbenchStateProvider runId={runId} validNodeKeys={validNodeKeys}>
      <LineageContext.Provider value={lineageCtx}>
        <div
          data-testid="workbench-route"
          style={{
            display: "flex",
            flexDirection: "column",
            height: "100%",
            minHeight: 0,
          }}
        >
          <WorkbenchTopbar />
          <WorkbenchMain />
          <BottomPanel runId={runId} projectRoot={projectRoot} />
          <ContextMenu />
          <SearchPalette />
        </div>
      </LineageContext.Provider>
    </WorkbenchStateProvider>
  );
}
