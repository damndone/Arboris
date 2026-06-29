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

import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
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
import type { RerunResponseV1 } from "../api";
import type { GraphViewNode, HeadSetNode } from "../lineage/api/graphViewTypes";

type PendingFocusTarget = {
  runId: string;
  focus: {
    forest_node_key: string | null;
    op_node_id: string;
    node_hash: string | null;
  };
  attempts: number;
};

const PENDING_FOCUS_RETRY_LIMIT = 20;
const PENDING_FOCUS_RETRY_DELAY_MS = 200;

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
  const [searchParams] = useSearchParams();
  const { forest, loading, error, refetch } = useForestData(projectRoot, runId);
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [pendingFocusTarget, setPendingFocusTarget] =
    useState<PendingFocusTarget | null>(null);
  const initializedPendingQueryKey = useRef<string | null>(null);

  const model = useMemo(
    () => (forest ? forestToGraphViewModel(forest, runId) : null),
    [forest, runId],
  );
  const validNodeKeys = useMemo<ReadonlySet<string> | undefined>(
    () => (model ? new Set(model.nodes.map((n) => n.nodeKey)) : undefined),
    [model],
  );

  const pendingSourceRunId = searchParams.get("pending_source_run_id");
  const pendingSourceModelNodeId = searchParams.get("pending_source_model_node_id");
  const pendingSourceOpNodeId = searchParams.get("pending_source_op_node_id");
  const pendingQueryKey =
    pendingSourceRunId && pendingSourceModelNodeId && pendingSourceOpNodeId
      ? `${runId}:${pendingSourceRunId}:${pendingSourceModelNodeId}:${pendingSourceOpNodeId}`
      : null;

  useEffect(() => {
    if (!pendingQueryKey || !pendingSourceOpNodeId) return;
    if (initializedPendingQueryKey.current === pendingQueryKey) return;
    initializedPendingQueryKey.current = pendingQueryKey;
    setActiveRunId(runId);
    setPendingFocusTarget({
      runId,
      focus: {
        forest_node_key: null,
        op_node_id: pendingSourceOpNodeId,
        node_hash: null,
      },
      attempts: 0,
    });
  }, [pendingQueryKey, pendingSourceOpNodeId, runId]);

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

  const handleRerun = (response: RerunResponseV1) => {
    const nextActiveRunId = response.new_active_head_id ?? response.run_id;
    setActiveRunId(nextActiveRunId);
    const lineage = response.produced_lineage;
    const focus = response.focus
      ? {
          forest_node_key: response.focus.forest_node_key,
          op_node_id: response.focus.op_node_id,
          node_hash: response.focus.node_hash,
        }
      : {
          forest_node_key: null,
          op_node_id: lineage?.produced_op_node_id ?? response.rerun_from.op_node_id,
          node_hash: lineage?.produced_node_hash ?? null,
        };
    setPendingFocusTarget({
      runId: nextActiveRunId,
      focus,
      attempts: 0,
    });
    void refetch();
  };

  return (
    <RerunProvider projectRoot={projectRoot} runId={effectiveActiveRunId} onRerun={handleRerun}>
      <ForestContext.Provider
        value={{ forest, activeRunId: effectiveActiveRunId, setActiveRunId }}
      >
        <WorkbenchStateProvider runId={runId} validNodeKeys={validNodeKeys}>
          <LineageBridge model={model}>
            <WorkbenchShell
              runId={runId}
              projectRoot={projectRoot}
              pendingFocusTarget={pendingFocusTarget}
              onPendingFocusConsumed={() => setPendingFocusTarget(null)}
              onPendingFocusRetry={() => {
                setPendingFocusTarget((current) =>
                  current === null
                    ? null
                    : { ...current, attempts: current.attempts + 1 },
                );
                void refetch();
              }}
            />
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

function resolvePendingFocusKey(
  nodes: GraphViewNode[],
  pending: PendingFocusTarget,
): string | null {
  const runNode = nodes.find(
    (node) =>
      isHeadSetNode(node) &&
      node.opNodeId === pending.focus.op_node_id &&
      node.runs.includes(pending.runId),
  );
  if (runNode) return runNode.nodeKey;

  const submittedKeyNode = nodes.find(
    (node) =>
      isHeadSetNode(node) &&
      node.nodeKey === pending.focus.forest_node_key &&
      node.runs.includes(pending.runId),
  );
  return submittedKeyNode?.nodeKey ?? null;
}

function isHeadSetNode(node: GraphViewNode): node is HeadSetNode {
  return "runs" in node && Array.isArray((node as HeadSetNode).runs);
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
  pendingFocusTarget = null,
  onPendingFocusConsumed,
  onPendingFocusRetry,
}: {
  runId: string;
  projectRoot: string;
  pendingFocusTarget?: PendingFocusTarget | null;
  onPendingFocusConsumed?: () => void;
  onPendingFocusRetry?: () => void;
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

  useEffect(() => {
    if (!pendingFocusTarget) return;
    const pendingFocusKey = resolvePendingFocusKey(model.nodes, pendingFocusTarget);
    if (!pendingFocusKey) {
      if (pendingFocusTarget.attempts >= PENDING_FOCUS_RETRY_LIMIT) return;
      const timer = window.setTimeout(() => {
        onPendingFocusRetry?.();
      }, PENDING_FOCUS_RETRY_DELAY_MS);
      return () => window.clearTimeout(timer);
    }
    select(pendingFocusKey);
    onPendingFocusConsumed?.();
  }, [
    model.nodes,
    onPendingFocusConsumed,
    onPendingFocusRetry,
    pendingFocusTarget,
    select,
  ]);

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
