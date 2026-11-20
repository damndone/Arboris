import "../lineage/tokens/lineage.css";
import "./panelHost.css";
import { NODE_PANEL_FLOATING_WIDTH, type NodePanelResizeState, type NodePanelUiState, PENDING_FOCUS_RETRY_DELAY_MS, PENDING_FOCUS_RETRY_LIMIT, type PanelPosition, type PendingFocusTarget, REPORT_REVIEW_FLOATING_WIDTH, RESIZE_HANDLES, type ReportReviewUiState, type ResizeCorner, findDockedFallbackTabId, persistNodePanelUiState, persistReportReviewUiState, readNodePanelUiState, readReportReviewUiState } from "./workbenchPanelUi";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { CSSProperties, KeyboardEvent as ReactKeyboardEvent, PointerEvent as ReactPointerEvent } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useLineage } from "../lineage/LineageContext";
import { ReportPreviewSelectionProvider } from "../lineage/api/reportPreviewSelection";
import { useGraphKeyboard } from "../lineage/hooks/useGraphKeyboard";
import { DetailDrawer } from "../lineage/detail/DetailDrawer";
import { DetailDrawerTabs } from "../lineage/detail/DetailDrawerTabs";
import { RawJsonModal } from "../lineage/modals/RawJsonModal";
import { useWorkbench } from "./WorkbenchStateProvider";
import { ContextMenu } from "./ContextMenu";
import { SelectionMenu } from "../workspace/SelectionMenu";
import { useGlobalShortcuts } from "./useGlobalShortcuts";
import { WorkbenchWorkspace } from "../workspace/WorkbenchWorkspace";
import { SearchPalette } from "./SearchPalette";
import { CommandPalette } from "./CommandPalette";
import type { GraphViewNode, HeadSetNode } from "../lineage/api/graphViewTypes";
import { AgentSurfaceProvider } from "./agent/AgentSurfaceContext";
import { PanelWindowControls, PanelWindowDragHandle } from "./PanelWindowControls";
import { REPORT_REVIEW_TAB_ID } from "./state/tabsSchema";
import { ReportReviewPanel } from "../report/ReportReviewPanel";
import { AgentNavigationContext, applyAgentNavigationRef } from "./agent/agentNavigation";
// Workbench route data, providers and shared node/report window state.
// The workspace owns the only layout; legacy run URLs enter the same shell.
// Draft execution, selection, overlays and pending-index recovery remain here.


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
export function WorkbenchShell({
  runId,
  projectRoot,
  onOpenGenesisWizard,
  hasGenesisDraft = false,
  pendingFocusTarget = null,
  onPendingFocusConsumed,
  onPendingFocusRetry,
  onOpenSettings,
}: {
  runId: string;
  projectRoot: string;
  onOpenGenesisWizard?: () => void;
  hasGenesisDraft?: boolean;
  pendingFocusTarget?: PendingFocusTarget | null;
  onPendingFocusConsumed?: () => void;
  onPendingFocusRetry?: () => void;
  onOpenSettings: () => void;
}) {
  const { model, selectedKey, select } = useLineage();
  const { state, dispatch } = useWorkbench();
  const navigate = useNavigate();
  const [navigationParams, setNavigationParams] = useSearchParams();
  const [rawJsonOpen, setRawJsonOpen] = useState(false);
  const [reportReviewUi, setReportReviewUi] = useState<ReportReviewUiState>(() => readReportReviewUiState(projectRoot));
  const [nodePanelUi, setNodePanelUi] = useState<NodePanelUiState>(() => readNodePanelUiState(projectRoot));
  const [reportReviewDragging, setReportReviewDragging] = useState(false);
  const [nodePanelDragging, setNodePanelDragging] = useState(false);
  const [nodePanelResizing, setNodePanelResizing] = useState(false);
  const [nodePanelSize, setNodePanelSize] = useState<{ width: number; height: number } | null>(null);
  const [reportFocusRequest, setReportFocusRequest] = useState(0);
  const reportReviewFloatingRef = useRef<HTMLDivElement | null>(null);
  const nodePanelFloatingRef = useRef<HTMLDivElement | null>(null);
  const reportReviewHydratedRootRef = useRef(projectRoot);
  const nodePanelHydratedRootRef = useRef(projectRoot);
  const reportReviewDragRef = useRef<{
    offsetX: number;
    offsetY: number;
    pointerId: number;
  } | null>(null);
  const nodePanelDragRef = useRef<{
    offsetX: number;
    offsetY: number;
    pointerId: number;
  } | null>(null);
  const nodePanelResizeRef = useRef<NodePanelResizeState | null>(null);

  useEffect(() => {
  }, [projectRoot]);

  useEffect(() => {
    reportReviewHydratedRootRef.current = projectRoot;
    setReportReviewUi(readReportReviewUiState(projectRoot));
  }, [projectRoot]);

  useEffect(() => {
    nodePanelHydratedRootRef.current = projectRoot;
    setNodePanelUi(readNodePanelUiState(projectRoot));
    setNodePanelSize(null);
  }, [projectRoot]);

  useEffect(() => {
    if (reportReviewHydratedRootRef.current !== projectRoot) return;
    persistReportReviewUiState(projectRoot, reportReviewUi);
  }, [projectRoot, reportReviewUi]);

  useEffect(() => {
    if (nodePanelHydratedRootRef.current !== projectRoot) return;
    persistNodePanelUiState(projectRoot, nodePanelUi);
  }, [nodePanelUi, projectRoot]);

  const reportReviewLayout = reportReviewUi.layout;
  const reportReviewPinned = reportReviewUi.pinned;
  const reportReviewCollapsed = reportReviewUi.collapsed;
  const reportReviewPosition = reportReviewUi.position;
  const nodePanelLayout = nodePanelUi.layout;
  const nodePanelPinned = nodePanelUi.pinned;
  const nodePanelCollapsed = nodePanelUi.collapsed;
  const nodePanelPosition = nodePanelUi.position;

  const floatReportReview = useCallback(() => {
    setReportReviewUi((state) => ({ ...state, layout: "floating", collapsed: false }));
  }, []);

  const dockReportReview = useCallback(() => {
    setReportReviewUi((state) => ({ ...state, layout: "docked", pinned: false, collapsed: false }));
  }, []);

  const pinReportReview = useCallback(() => {
    const width = Math.min(REPORT_REVIEW_FLOATING_WIDTH, Math.max(360, window.innerWidth - 32));
    setReportReviewUi((state) => ({
      ...state,
      layout: "floating",
      pinned: true,
      collapsed: false,
      position: state.layout === "floating"
        ? state.position
        : { x: Math.max(8, window.innerWidth - width - 16), y: 64 },
    }));
  }, []);

  const unpinReportReview = useCallback(() => {
    setReportReviewUi((state) => ({ ...state, pinned: false }));
  }, []);

  const beginReportReviewDrag = useCallback((event: ReactPointerEvent<HTMLButtonElement>) => {
    if (reportReviewLayout !== "floating" || reportReviewPinned) return;
    const panel = reportReviewFloatingRef.current;
    if (!panel) return;
    const rect = panel.getBoundingClientRect();
    event.preventDefault();
    reportReviewDragRef.current = {
      offsetX: event.clientX - rect.left,
      offsetY: event.clientY - rect.top,
      pointerId: event.pointerId,
    };
    event.currentTarget.setPointerCapture?.(event.pointerId);
    setReportReviewDragging(true);
  }, [reportReviewLayout, reportReviewPinned]);

  const moveReportReviewWithKeyboard = useCallback((event: ReactKeyboardEvent<HTMLButtonElement>) => {
    if (reportReviewLayout !== "floating" || reportReviewPinned) return;
    const step = event.shiftKey ? 64 : 16;
    const deltas: Record<string, PanelPosition> = {
      ArrowLeft: { x: -step, y: 0 },
      ArrowRight: { x: step, y: 0 },
      ArrowUp: { x: 0, y: -step },
      ArrowDown: { x: 0, y: step },
    };
    const delta = deltas[event.key];
    if (!delta) return;
    event.preventDefault();
    setReportReviewUi((state) => ({
      ...state,
      position: {
        x: Math.max(8, state.position.x + delta.x),
        y: Math.max(56, state.position.y + delta.y),
      },
    }));
  }, [reportReviewLayout, reportReviewPinned]);

  const moveReportReview = useCallback((event: globalThis.PointerEvent) => {
    const drag = reportReviewDragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    setReportReviewUi((state) => ({
      ...state,
      position: {
        x: Math.max(8, event.clientX - drag.offsetX),
        y: Math.max(56, event.clientY - drag.offsetY),
      },
    }));
  }, []);

  const stopReportReviewDrag = useCallback((event?: globalThis.PointerEvent) => {
    const drag = reportReviewDragRef.current;
    if (!drag || (event && drag.pointerId !== event.pointerId)) return;
    reportReviewDragRef.current = null;
    setReportReviewDragging(false);
  }, []);

  useEffect(() => {
    if (!reportReviewDragging) return undefined;
    window.addEventListener("pointermove", moveReportReview);
    window.addEventListener("pointerup", stopReportReviewDrag);
    window.addEventListener("pointercancel", stopReportReviewDrag);
    return () => {
      window.removeEventListener("pointermove", moveReportReview);
      window.removeEventListener("pointerup", stopReportReviewDrag);
      window.removeEventListener("pointercancel", stopReportReviewDrag);
    };
  }, [moveReportReview, reportReviewDragging, stopReportReviewDrag]);

  const floatNodePanel = useCallback(() => {
    const floatingTabId = state.selectedKey;
    if (!floatingTabId) return;
    const dockedFallbackTabId = findDockedFallbackTabId(
      state.tabs,
      state.activeTabId,
      floatingTabId,
    );
    setNodePanelUi((current) => ({
      ...current,
      layout: "floating",
      floatingTabId,
      collapsed: false,
    }));
    if (dockedFallbackTabId !== null) {
      dispatch.selectByTabSwitch(dockedFallbackTabId);
    }
  }, [dispatch, state.activeTabId, state.selectedKey, state.tabs]);

  const dockNodePanel = useCallback(() => {
    const detachedTabId = nodePanelUi.floatingTabId ?? state.selectedKey;
    setNodePanelUi((current) => ({
      ...current,
      layout: "docked",
      pinned: false,
      collapsed: false,
      floatingTabId: null,
    }));
    if (nodePanelLayout === "floating" && detachedTabId !== null && state.tabs.some((tab) => tab.id === detachedTabId)) {
      dispatch.selectByTabSwitch(detachedTabId);
    }
  }, [dispatch, nodePanelLayout, nodePanelUi.floatingTabId, state.selectedKey, state.tabs]);

  const pinNodePanel = useCallback(() => {
    const floatingTabId = nodePanelUi.floatingTabId ?? state.selectedKey;
    if (!floatingTabId) return;
    const width = Math.min(NODE_PANEL_FLOATING_WIDTH, Math.max(360, window.innerWidth - 32));
    const dockedFallbackTabId = findDockedFallbackTabId(
      state.tabs,
      state.activeTabId,
      floatingTabId,
    );
    setNodePanelUi((state) => ({
      ...state,
      layout: "floating",
      floatingTabId,
      pinned: true,
      collapsed: false,
      position: state.layout === "floating"
        ? state.position
        : { x: Math.max(8, window.innerWidth - width - 16), y: 64 },
    }));
    if (dockedFallbackTabId !== null) {
      dispatch.selectByTabSwitch(dockedFallbackTabId);
    }
  }, [dispatch, nodePanelUi.floatingTabId, state.activeTabId, state.selectedKey, state.tabs]);

  const unpinNodePanel = useCallback(() => {
    setNodePanelUi((state) => ({ ...state, pinned: false }));
  }, []);

  const beginNodePanelDrag = useCallback((event: ReactPointerEvent<HTMLButtonElement>) => {
    if (nodePanelLayout !== "floating" || nodePanelPinned) return;
    const panel = nodePanelFloatingRef.current;
    if (!panel) return;
    const rect = panel.getBoundingClientRect();
    event.preventDefault();
    nodePanelDragRef.current = {
      offsetX: event.clientX - rect.left,
      offsetY: event.clientY - rect.top,
      pointerId: event.pointerId,
    };
    event.currentTarget.setPointerCapture?.(event.pointerId);
    setNodePanelDragging(true);
  }, [nodePanelLayout, nodePanelPinned]);

  const moveNodePanelWithKeyboard = useCallback((event: ReactKeyboardEvent<HTMLButtonElement>) => {
    if (nodePanelLayout !== "floating" || nodePanelPinned) return;
    const step = event.shiftKey ? 64 : 16;
    const deltas: Record<string, PanelPosition> = {
      ArrowLeft: { x: -step, y: 0 },
      ArrowRight: { x: step, y: 0 },
      ArrowUp: { x: 0, y: -step },
      ArrowDown: { x: 0, y: step },
    };
    const delta = deltas[event.key];
    if (!delta) return;
    event.preventDefault();
    setNodePanelUi((state) => ({
      ...state,
      position: {
        x: Math.max(8, state.position.x + delta.x),
        y: Math.max(56, state.position.y + delta.y),
      },
    }));
  }, [nodePanelLayout, nodePanelPinned]);

  const moveNodePanel = useCallback((event: globalThis.PointerEvent) => {
    const drag = nodePanelDragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    setNodePanelUi((state) => ({
      ...state,
      position: {
        x: Math.max(8, event.clientX - drag.offsetX),
        y: Math.max(56, event.clientY - drag.offsetY),
      },
    }));
  }, []);

  const stopNodePanelDrag = useCallback((event?: globalThis.PointerEvent) => {
    const drag = nodePanelDragRef.current;
    if (!drag || (event && drag.pointerId !== event.pointerId)) return;
    nodePanelDragRef.current = null;
    setNodePanelDragging(false);
  }, []);

  const beginNodePanelResize = useCallback((corner: ResizeCorner, event: ReactPointerEvent<HTMLButtonElement>) => {
    if (nodePanelLayout !== "floating" || nodePanelCollapsed) return;
    const panel = nodePanelFloatingRef.current;
    if (!panel) return;
    const rect = panel.getBoundingClientRect();
    event.preventDefault();
    event.stopPropagation();
    nodePanelResizeRef.current = {
      corner,
      startX: event.clientX,
      startY: event.clientY,
      startWidth: rect.width,
      startHeight: rect.height,
      startLeft: rect.left,
      startTop: rect.top,
      pointerId: event.pointerId,
    };
    setNodePanelSize({ width: rect.width, height: rect.height });
    event.currentTarget.setPointerCapture?.(event.pointerId);
    setNodePanelResizing(true);
  }, [nodePanelCollapsed, nodePanelLayout]);

  const moveNodePanelResize = useCallback((event: globalThis.PointerEvent) => {
    const resize = nodePanelResizeRef.current;
    if (!resize || resize.pointerId !== event.pointerId) return;
    const deltaX = event.clientX - resize.startX;
    const deltaY = event.clientY - resize.startY;
    const growsLeft = resize.corner.includes("left");
    const growsTop = resize.corner.includes("top");
    const changesWidth = resize.corner !== "top" && resize.corner !== "bottom";
    const changesHeight = resize.corner !== "left" && resize.corner !== "right";
    const width = changesWidth
      ? Math.min(Math.max(360, window.innerWidth - 16), Math.max(360, resize.startWidth + (growsLeft ? -deltaX : deltaX)))
      : resize.startWidth;
    const height = changesHeight
      ? Math.min(Math.max(280, window.innerHeight - 56), Math.max(280, resize.startHeight + (growsTop ? -deltaY : deltaY)))
      : resize.startHeight;
    const left = growsLeft
      ? Math.max(8, resize.startLeft + resize.startWidth - width)
      : resize.startLeft;
    const top = growsTop
      ? Math.max(56, resize.startTop + resize.startHeight - height)
      : resize.startTop;
    setNodePanelSize({ width, height });
    setNodePanelUi((state) => ({
      ...state,
      position: { x: left, y: top },
    }));
  }, []);

  const stopNodePanelResize = useCallback((event?: globalThis.PointerEvent) => {
    const resize = nodePanelResizeRef.current;
    if (!resize || (event && resize.pointerId !== event.pointerId)) return;
    nodePanelResizeRef.current = null;
    setNodePanelResizing(false);
  }, []);

  useEffect(() => {
    if (!nodePanelDragging) return undefined;
    window.addEventListener("pointermove", moveNodePanel);
    window.addEventListener("pointerup", stopNodePanelDrag);
    window.addEventListener("pointercancel", stopNodePanelDrag);
    return () => {
      window.removeEventListener("pointermove", moveNodePanel);
      window.removeEventListener("pointerup", stopNodePanelDrag);
      window.removeEventListener("pointercancel", stopNodePanelDrag);
    };
  }, [moveNodePanel, nodePanelDragging, stopNodePanelDrag]);

  useEffect(() => {
    if (!nodePanelResizing) return undefined;
    window.addEventListener("pointermove", moveNodePanelResize);
    window.addEventListener("pointerup", stopNodePanelResize);
    window.addEventListener("pointercancel", stopNodePanelResize);
    return () => {
      window.removeEventListener("pointermove", moveNodePanelResize);
      window.removeEventListener("pointerup", stopNodePanelResize);
      window.removeEventListener("pointercancel", stopNodePanelResize);
    };
  }, [moveNodePanelResize, nodePanelResizing, stopNodePanelResize]);

  const openAgentNavigation = useMemo(
    () => (ref: Parameters<typeof applyAgentNavigationRef>[1]) => {
      if (!ref.available) return false;
      let destination = ref;
      if (ref.href.view === "graph" && !ref.href.forest_node_key && ref.href.node_ref) {
        const node = model.nodes.find(node => isHeadSetNode(node)
          ? node.opNodeId === ref.href.node_ref && node.runs.includes(ref.href.run_id ?? runId)
          : node.nodeKey === ref.href.node_ref && (!ref.href.run_id || ref.href.run_id === runId));
        if (node) destination = { ...ref, href: { ...ref.href, forest_node_key: node.nodeKey } };
      }
      setNavigationParams(applyAgentNavigationRef(navigationParams, destination));
      return true;
    },
    [model.nodes, navigationParams, runId, setNavigationParams],
  );

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
  const floatingNodeTabId = nodePanelLayout === "floating"
    ? nodePanelUi.floatingTabId ?? selectedNode?.id ?? null
    : null;
  const floatingNode = floatingNodeTabId !== null
    ? (nodeIndex.get(floatingNodeTabId) ?? null)
    : null;

  // Older session entries predate the detached-tab id. Recover that id from
  // the remembered selected node once the forest has loaded, without changing
  // the user's visible node selection.
  useEffect(() => {
    if (nodePanelLayout !== "floating" || nodePanelUi.floatingTabId !== null || selectedNode === null) return;
    setNodePanelUi((current) => (
      current.layout === "floating" && current.floatingTabId === null
        ? { ...current, floatingTabId: selectedNode.id }
        : current
    ));
  }, [nodePanelLayout, nodePanelUi.floatingTabId, selectedNode]);

  // If the detached tab is closed from its own floating tab strip, remove the
  // floating shell as well instead of silently replacing it with another node.
  useEffect(() => {
    if (floatingNodeTabId === null || state.tabs.some((tab) => tab.id === floatingNodeTabId)) return;
    setNodePanelUi((current) => ({
      ...current,
      layout: "docked",
      pinned: false,
      collapsed: false,
      floatingTabId: null,
    }));
  }, [floatingNodeTabId, state.tabs]);

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
    enabled: state.view !== "home",
  });

  // F6: global action-registry shortcut dispatcher (e.g. ⌘⇧C copy id).
  // Reuses F4's editable-target guard; acts on the selected node.
  useGlobalShortcuts({ enabled: state.view !== "home" });

  const reportReviewPanel = (
    <ReportReviewPanel
      floating={reportReviewLayout === "floating"}
      pinned={reportReviewPinned}
      collapsed={reportReviewLayout === "floating" && reportReviewCollapsed}
      dragging={reportReviewDragging}
      onFloat={floatReportReview}
      onDock={dockReportReview}
      onPin={pinReportReview}
      onUnpin={unpinReportReview}
      onCollapse={() => setReportReviewUi((state) => ({ ...state, collapsed: true }))}
      onExpand={() => setReportReviewUi((state) => ({ ...state, collapsed: false }))}
      onOpenReport={() => {
        dispatch.setView("report");
        setReportFocusRequest((request) => request + 1);
      }}
      onDragPointerDown={beginReportReviewDrag}
      onDragKeyDown={moveReportReviewWithKeyboard}
    />
  );
  const reportReviewFloating = reportReviewLayout === "floating" && typeof document !== "undefined"
    ? createPortal(
        <div
          ref={reportReviewFloatingRef}
          data-testid="report-review-floating"
          data-pinned={reportReviewPinned ? "true" : "false"}
          className={`report-review-floating${reportReviewPinned ? " report-review-floating--pinned" : ""}${reportReviewDragging ? " report-review-floating--dragging" : ""}${reportReviewCollapsed ? " report-review-floating--collapsed" : ""}`}
          style={{
            "--report-review-left": `${reportReviewPosition.x}px`,
            "--report-review-top": `${reportReviewPosition.y}px`,
          } as CSSProperties}
        >
          {reportReviewPanel}
        </div>,
        document.body,
      )
    : null;

  const dockedTabs = state.tabs.filter((tab) => tab.id !== floatingNodeTabId);
  const dockedActiveTabId = findDockedFallbackTabId(
    state.tabs,
    state.activeTabId,
    floatingNodeTabId,
  );
  const dockedActiveTab = dockedTabs.find((tab) => tab.id === dockedActiveTabId) ?? null;
  const reportReviewTabActive = dockedActiveTab?.id === REPORT_REVIEW_TAB_ID;
  const dockedSelectedNode = dockedActiveTab?.kind === "node"
    ? (nodeIndex.get(dockedActiveTab.id) ?? null)
    : null;
  const nodePanelTabActive = dockedSelectedNode !== null;
  const nodePanelWindowControls = (
    <PanelWindowControls
      surface="node panel"
      floating={nodePanelLayout === "floating"}
      pinned={nodePanelPinned}
      collapsed={nodePanelLayout === "floating" && nodePanelCollapsed}
      onFloat={floatNodePanel}
      onDock={dockNodePanel}
      onPin={pinNodePanel}
      onUnpin={unpinNodePanel}
      onCollapse={() => setNodePanelUi((current) => ({ ...current, collapsed: true }))}
      onExpand={() => setNodePanelUi((current) => ({ ...current, collapsed: false }))}
    />
  );
  const nodePanelWindowDragHandle = (
    <PanelWindowDragHandle
      surface="node panel"
      floating={nodePanelLayout === "floating"}
      pinned={nodePanelPinned}
      dragging={nodePanelDragging}
      onPointerDown={beginNodePanelDrag}
      onKeyDown={moveNodePanelWithKeyboard}
    />
  );
  const renderNodePanel = (node: GraphViewNode | null) => node !== null ? (
    <DetailDrawer
      node={node}
      projectRoot={projectRoot}
      onClose={() => select(null)}
      onShowJson={() => setRawJsonOpen(true)}
      windowControls={nodePanelWindowControls}
      windowDragHandle={nodePanelWindowDragHandle}
      collapsed={nodePanelLayout === "floating" && nodePanelCollapsed}
      showTabs={false}
      embedded
    />
  ) : null;
  const nodePanelContent = nodePanelLayout === "docked" ? renderNodePanel(dockedSelectedNode) : null;
  const floatingNodeTab = floatingNodeTabId !== null
    ? (state.tabs.find((tab) => tab.id === floatingNodeTabId) ?? null)
    : null;
  const closeFloatingNodeTab = (tabId: string) => {
    dispatch.closeTab(tabId);
    if (tabId !== floatingNodeTabId) return;
    setNodePanelUi((current) => ({
      ...current,
      layout: "docked",
      pinned: false,
      collapsed: false,
      floatingTabId: null,
    }));
  };
  const nodePanelFloating = nodePanelLayout === "floating"
    && floatingNode !== null
    && floatingNodeTab !== null
    && typeof document !== "undefined"
    ? createPortal(
        <div
          ref={nodePanelFloatingRef}
          data-testid="node-panel-floating"
          data-floating="true"
          data-pinned={nodePanelPinned ? "true" : "false"}
          data-collapsed={nodePanelCollapsed ? "true" : "false"}
          data-resizing={nodePanelResizing ? "true" : "false"}
          className={`node-panel-floating${nodePanelPinned ? " node-panel-floating--pinned" : ""}${nodePanelDragging || nodePanelResizing ? " node-panel-floating--dragging" : ""}${nodePanelCollapsed ? " node-panel-floating--collapsed" : ""}`}
          style={{
            "--node-panel-left": `${nodePanelPosition.x}px`,
            "--node-panel-top": `${nodePanelPosition.y}px`,
            ...(nodePanelSize !== null && !nodePanelCollapsed
              ? { width: `${nodePanelSize.width}px`, height: `${nodePanelSize.height}px` }
              : {}),
          } as CSSProperties}
        >
          <div className="node-panel-floating__surface">
            <div className="node-panel-floating__tabs">
              <DetailDrawerTabs
                tabs={[floatingNodeTab]}
                nodes={model.nodes}
                activeTabId={floatingNodeTabId}
                onActive={() => undefined}
                onClose={closeFloatingNodeTab}
              />
            </div>
            <div className="node-panel-floating__body">{renderNodePanel(floatingNode)}</div>
          </div>
          {!nodePanelCollapsed && RESIZE_HANDLES.map((corner) => (
            <button
              key={corner}
              type="button"
              tabIndex={-1}
              className={`node-panel-floating__resize-handle node-panel-floating__resize-handle--${corner}`}
              aria-label={`Resize node panel from ${corner}`}
              data-resize-corner={corner}
              onPointerDown={(event) => beginNodePanelResize(corner, event)}
            />
          ))}
        </div>,
        document.body,
      )
    : null;

  const overlays = (
    <>
      {state.view !== "home" && <ContextMenu />}
      <SelectionMenu />
      {<SearchPalette />}
      {<CommandPalette projectRoot={projectRoot} />}
      {state.view !== "home" && <RawJsonModal open={rawJsonOpen} onClose={() => setRawJsonOpen(false)} node={selectedNode} />}
      {reportReviewFloating}
      {nodePanelFloating}
    </>
  );
  const stageTabs = (
    <DetailDrawerTabs
      tabs={dockedTabs}
      nodes={model.nodes}
      activeTabId={dockedActiveTabId}
      onActive={dispatch.selectByTabSwitch}
      onClose={dispatch.closeTab}
      lastEvictedTabId={state.lastEvictedTabId}
    />
  );

  return (
    <ReportPreviewSelectionProvider key={projectRoot}>
      <AgentNavigationContext.Provider value={openAgentNavigation}>
        <AgentSurfaceProvider projectRoot={projectRoot} runId={runId}>
          <WorkbenchWorkspace
            runId={runId}
            projectRoot={projectRoot}
            stageTabs={stageTabs}
            stagePanelKind={reportReviewTabActive && reportReviewLayout === "docked" ? "report-review" : nodePanelTabActive ? "node" : null}
            stagePanel={reportReviewTabActive && reportReviewLayout === "docked" ? reportReviewPanel : nodePanelTabActive ? nodePanelContent : null}
            reportFocusRequest={reportFocusRequest}
            newAnalysis={onOpenGenesisWizard ? { label: hasGenesisDraft ? "Resume new analysis" : "New analysis", open: onOpenGenesisWizard } : undefined}
            onOpenSettings={onOpenSettings}
            overlays={overlays}
          />
        </AgentSurfaceProvider>
      </AgentNavigationContext.Provider>
    </ReportPreviewSelectionProvider>
  );
}

