// frontend/src/workbench/WorkbenchRouteContainer.tsx
//
// V1.5.2 P8 — full layout per plan §2.
//
//   <WorkbenchRouteContainer>
//     <WorkbenchStateProvider>
//       <LineageContext.Provider>
//         WorkbenchTopbar       (40px row)
//         ┌────────────────────────────────────────┐
//         │ RunHistoryRail   WorkbenchMain   Drawer │  (flex row, flex:1)
//         │ (240px)          (flex:1)        (320px)│
//         └────────────────────────────────────────┘
//         BottomPanel           (auto height, splitter)
//         <portals: ContextMenu, SearchPalette, RawJsonModal>
//
// What this container owns:
//   - data load (useGraphData)
//   - loading / error branching
//   - both providers
//   - RunHistoryRail mount (shared across all views)
//   - DetailDrawer mount + ⌘J / Escape keyboard
//   - RawJsonModal mount (selection-scoped, not canvas-scoped)
//
// GraphView is now slim: canvas + legacy banner + legacy hint only.
// Table / Pipeline views compose into the same shell so the drawer +
// rail + panel + search palette work identically across them.

import { useEffect, useMemo, useState } from "react";
import { useGraphData } from "../lineage/hooks/useGraphData";
import { useLineage } from "../lineage/LineageContext";
import { ErrorBanner, Loading } from "../lineage/statusViews";
import { useGraphKeyboard } from "../lineage/hooks/useGraphKeyboard";
import { DetailDrawer } from "../lineage/detail/DetailDrawer";
import { RawJsonModal } from "../lineage/modals/RawJsonModal";
import { RunHistoryRail } from "../lineage/runRail/RunHistoryRail";
import "../lineage/tokens/lineage.css";
import { WorkbenchStateProvider } from "./WorkbenchStateProvider";
import { LineageBridge } from "./LineageBridge";
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

  const validNodeKeys = useMemo<ReadonlySet<string> | undefined>(() => {
    if (model === null) return undefined;
    return new Set(model.nodes.map((n) => n.nodeKey));
  }, [model]);

  if (loading) return <Loading />;
  if (error !== null) return <ErrorBanner error={error} onRetry={refetch} />;
  if (model === null) return <Loading />;

  return (
    <WorkbenchStateProvider runId={runId} validNodeKeys={validNodeKeys}>
      <LineageBridge model={model}>
        <WorkbenchShell runId={runId} projectRoot={projectRoot} />
      </LineageBridge>
    </WorkbenchStateProvider>
  );
}

/**
 * Inner shell — split out so it can consume both contexts via hooks
 * (useLineage + useWorkbench) without putting the providers' children
 * inside a useMemo that would re-render the whole tree on every
 * selection change.
 */
function WorkbenchShell({
  runId,
  projectRoot,
}: {
  runId: string;
  projectRoot: string;
}) {
  const { model, selectedKey, select } = useLineage();
  const [rawJsonOpen, setRawJsonOpen] = useState(false);

  // Selected-node lookup with the V1.5.0 cross-run leak guard
  // (see V1.5.0 GraphWorkbench REV-3 #3). selectedKey may point at a
  // node from a previous run if the user navigated /runs/A?node=x
  // → /runs/B; suppress the drawer entirely in that case.
  const nodeIndex = useMemo(
    () => new Map(model.nodes.map((n) => [n.id, n])),
    [model.nodes],
  );
  const effectiveSelectedKey =
    selectedKey !== null && nodeIndex.has(selectedKey) ? selectedKey : null;
  const selectedNode =
    effectiveSelectedKey !== null
      ? (nodeIndex.get(effectiveSelectedKey) ?? null)
      : null;

  // REV-3 H1: external selection clear must close the modal.
  useEffect(() => {
    if (selectedNode === null && rawJsonOpen) setRawJsonOpen(false);
  }, [selectedNode, rawJsonOpen]);

  // ⌘J / Escape — selection-scoped, not view-scoped. Living at
  // container level means the shortcut works identically in
  // Graph / Table / Pipeline views.
  useGraphKeyboard({
    onToggleRawJson: () => {
      if (selectedNode === null) return;
      setRawJsonOpen((v) => !v);
    },
    onEscape: () => {
      // REV-3 S1: modal owns its own Escape; skip when modal open.
      if (rawJsonOpen) return;
      select(null);
    },
    onCmdK: () => {
      /* SearchPalette owns its own ⌘K listener (V1.5.2 P7) */
    },
  });

  return (
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
      <div
        style={{
          display: "flex",
          flexDirection: "row",
          flex: 1,
          minHeight: 0,
        }}
      >
        <RunHistoryRail />
        <WorkbenchMain />
        {selectedNode !== null && (
          <DetailDrawer
            node={selectedNode}
            onClose={() => select(null)}
            onShowJson={() => setRawJsonOpen(true)}
          />
        )}
      </div>
      <BottomPanel runId={runId} projectRoot={projectRoot} />
      <ContextMenu />
      <SearchPalette />
      <RawJsonModal
        open={rawJsonOpen}
        onClose={() => setRawJsonOpen(false)}
        node={selectedNode}
      />
    </div>
  );
}
