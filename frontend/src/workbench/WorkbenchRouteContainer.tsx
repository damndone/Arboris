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
import { useGlobalShortcuts } from "./useGlobalShortcuts";
import { BottomPanel } from "./BottomPanel";
import { SearchPalette } from "./SearchPalette";
import { CommandPalette } from "./CommandPalette";
import { useForestData } from "../lineage/hooks/useForestData";
import { forestToGraphViewModel } from "./forestModel";
import { ForestContext } from "./ForestContext";
import { RerunProvider } from "../lineage/detail/RerunContext";

interface WorkbenchRouteContainerProps {
  projectRoot: string;
  runId: string;
}

export function WorkbenchRouteContainer({
  projectRoot,
  runId,
}: WorkbenchRouteContainerProps) {
  // v1.6.1 — the lineage graph IS the cross-run forest. Always render the forest; it
  // falls back to the legacy per-run graph only for old runs that predate the lineage
  // index (no node_index.json). No toggle: a run with no reruns is simply a linear
  // forest, which is cleaner than the old per-run graph's variable folding.
  return <ForestWorkbench projectRoot={projectRoot} runId={runId} />;
}

function ForestWorkbench({ projectRoot, runId }: WorkbenchRouteContainerProps) {
  const { forest, loading, error, refetch } = useForestData(projectRoot, runId);
  const [activeRunId, setActiveRunId] = useState<string | null>(null);

  const model = useMemo(
    () => (forest ? forestToGraphViewModel(forest, runId) : null),
    [forest, runId],
  );
  const validNodeKeys = useMemo<ReadonlySet<string> | undefined>(
    () => (model ? new Set(model.nodes.map((n) => n.nodeKey)) : undefined),
    [model],
  );

  if (error !== null && forest === null) {
    return <ErrorBanner error={error} onRetry={refetch} />;
  }
  if (loading || forest === null || model === null) return <Loading />;
  // Legacy target (no node identity) → fall back to the legacy per-run workbench.
  if (forest.legacy) {
    return <LegacyGraphWorkbench projectRoot={projectRoot} runId={runId} />;
  }

  const effectiveActiveRunId =
    activeRunId ??
    forest.heads.find((h) => h.runId === runId)?.runId ??
    forest.heads[forest.heads.length - 1]?.runId ??
    runId;

  return (
    <RerunProvider projectRoot={projectRoot} runId={runId} onRerun={() => refetch()}>
      <ForestContext.Provider
        value={{ forest, activeRunId: effectiveActiveRunId, setActiveRunId }}
      >
        <WorkbenchStateProvider runId={runId} validNodeKeys={validNodeKeys}>
          <LineageBridge model={model}>
            <WorkbenchShell runId={runId} projectRoot={projectRoot} />
          </LineageBridge>
        </WorkbenchStateProvider>
      </ForestContext.Provider>
    </RerunProvider>
  );
}

function LegacyGraphWorkbench({
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

  // F6: global action-registry shortcut dispatcher (e.g. ⌘⇧C copy id).
  // Reuses F4's editable-target guard; acts on the selected node.
  useGlobalShortcuts();

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
      <CommandPalette />
      <RawJsonModal
        open={rawJsonOpen}
        onClose={() => setRawJsonOpen(false)}
        node={selectedNode}
      />
    </div>
  );
}
