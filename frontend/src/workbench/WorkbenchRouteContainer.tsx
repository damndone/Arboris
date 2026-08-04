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

import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { CSSProperties, KeyboardEvent as ReactKeyboardEvent, PointerEvent as ReactPointerEvent } from "react";
import {
  useLocation,
  useNavigate,
  useOutletContext,
  useSearchParams,
} from "react-router-dom";
import { useGraphData } from "../lineage/hooks/useGraphData";
import { useLineage } from "../lineage/LineageContext";
import { ErrorBanner, Loading } from "../lineage/statusViews";
import { useGraphKeyboard } from "../lineage/hooks/useGraphKeyboard";
import { DetailDrawer } from "../lineage/detail/DetailDrawer";
import { DetailDrawerTabs } from "../lineage/detail/DetailDrawerTabs";
import { RawJsonModal } from "../lineage/modals/RawJsonModal";
import {
  RunHistoryRail,
  persistRunHistoryOpen,
  readRunHistoryOpen,
} from "../lineage/runRail/RunHistoryRail";
import "../lineage/tokens/lineage.css";
import { WorkbenchStateProvider } from "./WorkbenchStateProvider";
import { useWorkbench, type WorkbenchState } from "./WorkbenchStateProvider";
import { rootToSlug } from "./projectSlug";
import { CompareProvider } from "../lineage/compare/CompareContext";
import { LineageBridge } from "./LineageBridge";
import { ProjectSwitcher, WorkbenchTopbar } from "./WorkbenchTopbar";
import { WorkbenchMain } from "./WorkbenchMain";
import { WorkbenchHomeView } from "./views/WorkbenchHomeView";
import { ContextMenu } from "./ContextMenu";
import { useGlobalShortcuts } from "./useGlobalShortcuts";
import { BottomPanel } from "./BottomPanel";
import { SearchPalette } from "./SearchPalette";
import { CommandPalette } from "./CommandPalette";
import { ProjectRootProvider } from "./ProjectRootContext";
import { RailRefreshContext } from "./RailRefreshContext";
import { useForestData } from "../lineage/hooks/useForestData";
import { forestToGraphViewModel } from "./forestModel";
import { ForestContext } from "./ForestContext";
import { RerunProvider } from "../lineage/detail/RerunContext";
import { LlmProviderManager } from "../llm/LlmProviderManager";
import { draftReducer, emptyRegistry } from "../lineage/drafts/draftRegistry";
import { mergeDraftsIntoModel } from "../lineage/drafts/mergeDraftsIntoModel";
import { DraftActionsProvider } from "../lineage/drafts/DraftActionsContext";
import { GenesisWizard } from "../lineage/drafts/GenesisWizard";
import { useDraftHandlers } from "./useDraftHandlers";
import {
  getRunGraphHeadSet,
  fetchRunDetail,
  executePipelineDraft,
  deletePipelineDraft,
  waitForRunTerminal,
  type RerunResponseV1,
  type DraftExecutionResult,
} from "../api";
import { completeNotebookOptionExecution } from "../notebook/notebookApi";
import type { GraphViewNode, HeadSetNode } from "../lineage/api/graphViewTypes";
import { usePendingRun, type PendingRun } from "./usePendingRun";
import { AgentSurfaceProvider } from "./agent/AgentSurfaceContext";
import { PanelHost } from "./PanelHost";
import "./panelHost.css";
import { PanelWindowControls, PanelWindowDragHandle } from "./PanelWindowControls";
import { REPORT_REVIEW_TAB_ID } from "./state/tabsSchema";
import {
  ReportReviewPanel,
} from "../report/ReportReviewPanel";
import { ReportWorkspaceProvider } from "../report/ReportWorkspaceContext";
import {
  AgentNavigationContext,
  applyAgentNavigationRef,
} from "./agent/agentNavigation";
import { registerBuiltinFeatureViews } from "./agent/builtinFeatureViews";
import { NotebookRouteView } from "../notebook/NotebookRouteView";
import type { NotebookMaterializationResponse } from "../notebook/notebookApi";

type PendingFocusTarget = {
  runId: string;
  focus: {
    forest_node_key: string | null;
    op_node_id: string;
    node_hash: string | null;
  };
  attempts: number;
};

type LegacyFocusProbe = {
  key: string;
  loading: boolean;
  kind: "blocked" | "legacy" | "not_indexed";
};

const PENDING_FOCUS_RETRY_LIMIT = 20;
const PENDING_FOCUS_RETRY_DELAY_MS = 200;

type PanelLayout = "docked" | "floating";

type PanelPosition = {
  x: number;
  y: number;
};

type ResizeCorner = "top-left" | "top-right" | "bottom-left" | "bottom-right";

type NodePanelResizeState = {
  corner: ResizeCorner;
  startX: number;
  startY: number;
  startWidth: number;
  startHeight: number;
  startLeft: number;
  startTop: number;
  pointerId: number;
};

type PanelUiState = {
  layout: PanelLayout;
  pinned: boolean;
  collapsed: boolean;
  position: PanelPosition;
  /** The tab detached into the floating node window, when applicable. */
  floatingTabId: string | null;
};

type ReportReviewUiState = PanelUiState;
type NodePanelUiState = PanelUiState;

const REPORT_REVIEW_FLOATING_WIDTH = 680;
const NODE_PANEL_FLOATING_WIDTH = 680;
const REPORT_REVIEW_STORAGE_PREFIX = "workbench:report-review:";
const NODE_PANEL_STORAGE_PREFIX = "workbench:node-panel:";
const DEFAULT_REPORT_REVIEW_UI_STATE: ReportReviewUiState = {
  layout: "docked",
  pinned: false,
  collapsed: false,
  position: { x: 36, y: 116 },
  floatingTabId: null,
};
const DEFAULT_NODE_PANEL_UI_STATE: NodePanelUiState = {
  layout: "docked",
  pinned: false,
  collapsed: false,
  position: { x: 36, y: 116 },
  floatingTabId: null,
};

function reportReviewStorageKey(projectRoot: string): string {
  return `${REPORT_REVIEW_STORAGE_PREFIX}${projectRoot}`;
}

function nodePanelStorageKey(projectRoot: string): string {
  return `${NODE_PANEL_STORAGE_PREFIX}${projectRoot}`;
}

function readPanelUiState(storageKey: string, fallback: PanelUiState): PanelUiState {
  if (typeof sessionStorage === "undefined") return fallback;
  try {
    const raw = sessionStorage.getItem(storageKey);
    if (!raw) return fallback;
    const parsed = JSON.parse(raw) as Partial<PanelUiState>;
    const position = parsed.position;
    return {
      layout: parsed.layout === "floating" ? "floating" : "docked",
      pinned: parsed.pinned === true,
      collapsed: parsed.collapsed === true,
      floatingTabId: typeof parsed.floatingTabId === "string" ? parsed.floatingTabId : fallback.floatingTabId,
      position: {
        x: typeof position?.x === "number" && Number.isFinite(position.x)
          ? Math.max(8, position.x)
          : fallback.position.x,
        y: typeof position?.y === "number" && Number.isFinite(position.y)
          ? Math.max(56, position.y)
          : fallback.position.y,
      },
    };
  } catch {
    return fallback;
  }
}

function findDockedFallbackTabId(
  tabs: WorkbenchState["tabs"],
  activeTabId: string | null,
  floatingTabId: string | null,
): string | null {
  const dockedTabs = tabs.filter((tab) => tab.id !== floatingTabId);
  if (dockedTabs.length === 0) return null;
  if (activeTabId !== floatingTabId && dockedTabs.some((tab) => tab.id === activeTabId)) {
    return activeTabId;
  }

  const activeIndex = tabs.findIndex((tab) => tab.id === activeTabId);
  if (activeIndex >= 0) {
    const next = tabs.slice(activeIndex + 1).find((tab) => tab.id !== floatingTabId);
    if (next) return next.id;
    const previous = tabs.slice(0, activeIndex).reverse().find((tab) => tab.id !== floatingTabId);
    if (previous) return previous.id;
  }
  return dockedTabs[0].id;
}

function readReportReviewUiState(projectRoot: string): ReportReviewUiState {
  return readPanelUiState(reportReviewStorageKey(projectRoot), DEFAULT_REPORT_REVIEW_UI_STATE);
}

function readNodePanelUiState(projectRoot: string): NodePanelUiState {
  return readPanelUiState(nodePanelStorageKey(projectRoot), DEFAULT_NODE_PANEL_UI_STATE);
}

function persistPanelUiState(storageKey: string, state: PanelUiState): void {
  if (typeof sessionStorage === "undefined") return;
  try {
    sessionStorage.setItem(storageKey, JSON.stringify(state));
  } catch {
    // A private browsing context can reject sessionStorage; the UI remains usable.
  }
}

function persistReportReviewUiState(projectRoot: string, state: ReportReviewUiState): void {
  persistPanelUiState(reportReviewStorageKey(projectRoot), state);
}

function persistNodePanelUiState(projectRoot: string, state: NodePanelUiState): void {
  persistPanelUiState(nodePanelStorageKey(projectRoot), state);
}

// A draft-execute focus that never recorded a produced op node id degrades to
// "no target": the pending-focus effect then simply finds nothing and gives up
// after its budget instead of crashing — the run still activated + indexed.
const EMPTY_FOCUS: PendingFocusTarget["focus"] = {
  forest_node_key: null,
  op_node_id: "",
  node_hash: null,
};

interface WorkbenchHomeProps {
  projectRoot: string;
  /** Optional run deep link (?run=). Absent → newest head is the active run;
   *  a zero-run project renders the empty canvas + genesis CTA instead. */
  focusRunId?: string;
  /** One-shot upload handoff from launcher and compatibility routes. */
  openGenesis?: boolean;
  /** Monotonic request from the outer project navigation. */
  settingsRequestVersion?: number;
}

type AppShellStatusContext = {
  setError?: (message: string | null) => void;
};

/** v1.6.8 T11 — the project-keyed workbench home. The forest is keyed by
 *  projectRoot alone; runId is only an optional focus hint. */
export function WorkbenchHome({
  projectRoot,
  focusRunId,
  openGenesis = false,
  settingsRequestVersion = 0,
}: WorkbenchHomeProps) {
  // This is the live project-home mount path. The bootstrap itself is
  // idempotent so React StrictMode and route remounts cannot duplicate a view.
  useEffect(() => {
    registerBuiltinFeatureViews();
  }, []);

  // v1.6.8 — the project home renders the project forest. A run deep link is
  // only a focus hint; if that run is absent from the project forest, probe the
  // old run-keyed headset once so true legacy runs can still use the legacy
  // per-run workbench.
  return (
    <ForestWorkbench
      projectRoot={projectRoot}
      focusRunId={focusRunId}
      openGenesis={openGenesis}
      settingsRequestVersion={settingsRequestVersion}
    />
  );
}

interface WorkbenchRouteContainerProps {
  projectRoot: string;
  runId: string;
}

/** Legacy per-run entry point (runDetail.tsx / LineageRouteContainer.tsx still
 *  pass a required runId). Same component; runId becomes the focus hint. */
export function WorkbenchRouteContainer({
  projectRoot,
  runId,
}: WorkbenchRouteContainerProps) {
  return <WorkbenchHome projectRoot={projectRoot} focusRunId={runId} />;
}

function ForestWorkbench({
  projectRoot,
  focusRunId,
  openGenesis = false,
  settingsRequestVersion = 0,
}: WorkbenchHomeProps) {
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const { forest, loading, error, refetch } = useForestData(projectRoot);
  const appShellContext = useOutletContext<AppShellStatusContext>();
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [pendingFocusTarget, setPendingFocusTarget] =
    useState<PendingFocusTarget | null>(null);
  const [legacyFocusProbe, setLegacyFocusProbe] =
    useState<LegacyFocusProbe | null>(null);
  const [focusIndexPollAttempts, setFocusIndexPollAttempts] = useState(0);
  const [genesisWizardOpen, setGenesisWizardOpen] = useState(openGenesis);
  const genesisHandoffConsumed = useRef(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const previousSettingsRequest = useRef(settingsRequestVersion);
  const [pendingGenesisRun, setPendingGenesisRun] =
    useState<PendingRun | null>(null);
  // v1.6.9 B1 — draft-execute rides the same index-wait layer as genesis. The
  // produced run is a background async job (a long run indexes minutes later),
  // so the draft node must stay on the canvas until the run actually indexes
  // rather than vanishing the instant the execute POST returns. The focus
  // target is captured at execute time (the forest has no produced node yet)
  // and consumed by onIndexed once the run appears.
  const [pendingRerunRun, setPendingRerunRun] = useState<PendingRun | null>(
    null,
  );
  const pendingRerunFocus = useRef<PendingFocusTarget["focus"] | null>(null);
  const initializedPendingQueryKey = useRef<string | null>(null);
  const [registry, dispatchDraft] = useReducer(draftReducer, undefined, emptyRegistry);
  const [draftBusy, setDraftBusy] = useState(false);
  // v1.6.9 B1-4 — monotonic token handed to the RUNS rail via RailRefreshContext.
  // Bumped in the pending-run onIndexed callbacks so the rail re-fetches /runs the
  // instant a genesis / draft-execute run indexes, rather than lagging its 30s poll.
  const [railRefreshToken, setRailRefreshToken] = useState(0);
  const focusRunIsKnownHead = useMemo(
    () => Boolean(focusRunId && forest?.heads.some((h) => h.runId === focusRunId)),
    [forest, focusRunId],
  );

  useEffect(() => {
    if (previousSettingsRequest.current === settingsRequestVersion) return;
    previousSettingsRequest.current = settingsRequestVersion;
    setSettingsOpen(true);
  }, [settingsRequestVersion]);

  // Notebook memory is configured from the shared Settings surface. Keep the
  // navigation intent in the URL so a view remount cannot lose it, then remove
  // it once consumed so back/refresh does not repeatedly reopen Settings.
  useEffect(() => {
    if (searchParams.get("memory_settings") !== "1") return;
    setSettingsOpen(true);
    const next = new URLSearchParams(searchParams);
    next.delete("memory_settings");
    setSearchParams(next, { replace: true });
  }, [searchParams, setSearchParams]);

  // A run can be terminal before the project forest scanner has written its
  // head-set entry. Keep a focused deep link alive through that short window
  // instead of making the user refresh the page manually.
  useEffect(() => {
    if (!appShellContext?.setError) return;
    if (error?.kind === "not_found") {
      appShellContext.setError("Project not found");
      return;
    }
    appShellContext.setError(null);
  }, [appShellContext?.setError, error]);

  useEffect(() => {
    if (!focusRunId || !forest || focusRunIsKnownHead) {
      if (focusIndexPollAttempts !== 0) setFocusIndexPollAttempts(0);
      return undefined;
    }
    if (focusIndexPollAttempts >= 30) return undefined;
    const timer = window.setTimeout(() => {
      setFocusIndexPollAttempts((attempts) => attempts + 1);
      void refetch();
    }, 1000);
    return () => window.clearTimeout(timer);
  }, [
    focusIndexPollAttempts,
    focusRunId,
    focusRunIsKnownHead,
    forest,
    refetch,
  ]);

  // The run the workbench treats as "the" run when no explicit focus exists:
  // newest head by created_at (the project forest unions families in run-id
  // order, so array position is NOT chronological across families).
  const newestHeadRunId = useMemo(() => {
    const heads = forest?.heads ?? [];
    if (heads.length === 0) return undefined;
    return [...heads].sort((a, b) =>
      (b.createdAt ?? "").localeCompare(a.createdAt ?? ""),
    )[0].runId;
  }, [forest]);
  const resolvedRunId =
    focusRunId && focusRunIsKnownHead ? focusRunId : newestHeadRunId;

  // `?genesis=1` is a one-shot handoff instruction from project creation, not
  // state: open the wizard, then strip the param so reloads and unrelated
  // query updates don't reopen a wizard the user already closed.
  useEffect(() => {
    const queryGenesis =
      searchParams.get("genesis") === "1" ||
      searchParams.get("open_genesis") === "1";
    if ((!openGenesis && !queryGenesis) || genesisHandoffConsumed.current) return;
    genesisHandoffConsumed.current = true;
    setGenesisWizardOpen(true);
  }, [genesisHandoffConsumed, openGenesis, searchParams]);

  const closeGenesisWizard = useCallback(() => {
    setGenesisWizardOpen(false);
    if (
      searchParams.get("genesis") !== "1" &&
      searchParams.get("open_genesis") !== "1"
    ) return;
    const next = new URLSearchParams(searchParams);
    next.delete("genesis");
    next.delete("open_genesis");
    setSearchParams(next, { replace: true });
  }, [searchParams, setSearchParams]);

  const legacyFocusProbeKey =
    forest && focusRunId && !focusRunIsKnownHead
      ? `${projectRoot}\u0000${focusRunId}`
      : null;

  useEffect(() => {
    if (!legacyFocusProbeKey || !focusRunId) {
      return undefined;
    }
    let cancelled = false;
    setLegacyFocusProbe({ key: legacyFocusProbeKey, loading: true, kind: "not_indexed" });
    Promise.allSettled([
      getRunGraphHeadSet(projectRoot, focusRunId),
      fetchRunDetail(projectRoot, focusRunId),
    ])
      .then(([headSetResult, detailResult]) => {
        if (cancelled) return;
        setLegacyFocusProbe({
          key: legacyFocusProbeKey,
          loading: false,
          kind:
            detailResult.status === "fulfilled" && detailResult.value.status === "blocked"
              ? "blocked"
              : headSetResult.status === "fulfilled" &&
                    (headSetResult.value.legacy === true || !Array.isArray(headSetResult.value.heads))
                ? "legacy"
                : "not_indexed",
        });
      })
      .catch(() => {
        if (cancelled) return;
        setLegacyFocusProbe({
          key: legacyFocusProbeKey,
          loading: false,
          kind: "not_indexed",
        });
      });
    return () => {
      cancelled = true;
    };
  }, [focusRunId, legacyFocusProbeKey, projectRoot]);

  const visibleDraftIds = useMemo<ReadonlySet<string> | undefined>(() => {
    const values = [searchParams.get("active"), searchParams.get("focus"), searchParams.get("tabs")]
      .filter((value): value is string => Boolean(value))
      .flatMap((value) => value.split(","));
    const draftIds = new Set(values.flatMap((value) => {
      if (!value.startsWith("draft:")) return [];
      const draftId = value.slice("draft:".length).split(":")[0];
      return draftId ? [draftId] : [];
    }));
    // An empty set means the URL did not request a draft filter. Passing that
    // empty set to mergeDraftsIntoModel hid every hydrated draft, including a
    // persisted genesis draft in a zero-run project.
    return draftIds.size > 0 ? draftIds : undefined;
  }, [searchParams]);

  const model = useMemo(
    () => {
      const base = forest
        ? forestToGraphViewModel(forest, resolvedRunId ?? "")
        : null;
      return base ? mergeDraftsIntoModel(base, registry, { visibleDraftIds }) : null;
    },
    [forest, resolvedRunId, registry, visibleDraftIds],
  );
  const validNodeKeys = useMemo<ReadonlySet<string> | undefined>(
    () => (model ? new Set(model.nodes.map((n) => n.nodeKey)) : undefined),
    [model],
  );

  // v1.6.9 B1-3 — draft fork/patch/validate/discard/ensure-loaded + genesis
  // pure dispatches + the mount-time hydration effect live in the hook (spec
  // §4.4 cohesion cluster). Registry + busy state stay here so handleExecuteDraft
  // (which owns container-level pending-run state) reads them directly.
  const draftHandlers = useDraftHandlers({
    projectRoot,
    registry,
    dispatchDraft,
    setDraftBusy,
  });

  // Reset the in-graph active head when the URL run changes (rail navigation to
  // a different forest root). Without this, an active head set by a prior
  // in-graph execute sticks and misleads views that follow the active head
  // (e.g. the Table view would keep showing the executed run after the user
  // navigates to a different run). Declared BEFORE the pending-focus effect so
  // the deep-link pending path can still re-set activeRunId=runId afterward.
  useEffect(() => {
    setActiveRunId(null);
  }, [focusRunId]);

  // Deep-link pending focus (post-draft-execute navigation). Keyed on the
  // RESOLVED run: the pending params always travel with an explicit ?run=
  // (the execute flow navigates to the produced run), but guard on
  // resolvedRunId anyway — with no resolvable run there is nothing to focus.
  const pendingSourceRunId = searchParams.get("pending_source_run_id");
  const pendingSourceModelNodeId = searchParams.get("pending_source_model_node_id");
  const pendingSourceOpNodeId = searchParams.get("pending_source_op_node_id");
  const pendingQueryKey =
    resolvedRunId &&
    pendingSourceRunId &&
    pendingSourceModelNodeId &&
    pendingSourceOpNodeId
      ? `${resolvedRunId}:${pendingSourceRunId}:${pendingSourceModelNodeId}:${pendingSourceOpNodeId}`
      : null;

  useEffect(() => {
    if (!pendingQueryKey || !pendingSourceOpNodeId || !resolvedRunId) return;
    if (initializedPendingQueryKey.current === pendingQueryKey) return;
    initializedPendingQueryKey.current = pendingQueryKey;
    setActiveRunId(resolvedRunId);
    setPendingFocusTarget({
      runId: resolvedRunId,
      focus: {
        forest_node_key: null,
        op_node_id: pendingSourceOpNodeId,
        node_hash: null,
      },
      attempts: 0,
    });
  }, [pendingQueryKey, pendingSourceOpNodeId, resolvedRunId]);

  // v1.6.9 B1 — genesis rides the shared index-wait layer. onIndexed reproduces
  // the original inline behavior EXACTLY: activate the produced run, remove the
  // draft node, clear pending, and close the wizard. onFailed marks the draft
  // failed (the hook clears pending itself). The draftId travels in pending, so
  // these inline arrows read the fresh value from pendingGenesisRun each render.
  usePendingRun({
    pending: pendingGenesisRun,
    projectRoot,
    forest,
    refetch: () => void refetch(),
    onIndexed: (runId) => {
      setActiveRunId(runId);
      if (pendingGenesisRun) {
        dispatchDraft({ type: "remove", draftId: pendingGenesisRun.draftId });
      }
      setPendingGenesisRun(null);
      setGenesisWizardOpen(false);
      setRailRefreshToken((t) => t + 1);
    },
    onFailed: (draftId) => {
      dispatchDraft({ type: "failed", draftId });
    },
    setPending: setPendingGenesisRun,
  });

  // v1.6.9 B1 — draft-execute index-wait. onIndexed activates the produced run,
  // NOW (not at POST time) sets the pending focus, removes the draft node, and
  // best-effort deletes the persisted draft. onFailed marks the draft failed so
  // a terminal-failed run shows on the canvas instead of vanishing silently.
  usePendingRun({
    pending: pendingRerunRun,
    projectRoot,
    forest,
    refetch: () => void refetch(),
    onIndexed: (runId) => {
      setActiveRunId(runId);
      setPendingFocusTarget({
        runId,
        focus: pendingRerunFocus.current ?? EMPTY_FOCUS,
        attempts: 0,
      });
      if (pendingRerunRun) {
        const draftId = pendingRerunRun.draftId;
        dispatchDraft({ type: "remove", draftId });
        void deletePipelineDraft(projectRoot, draftId).catch((e) =>
          console.error("draft cleanup (delete) failed post-execute", e),
        );
      }
      setPendingRerunRun(null);
      setRailRefreshToken((t) => t + 1);
    },
    onFailed: (draftId) => {
      dispatchDraft({ type: "failed", draftId });
    },
    setPending: setPendingRerunRun,
  });

  if (settingsOpen) {
    return <LlmProviderManager projectRoot={projectRoot} onBack={() => setSettingsOpen(false)} />;
  }
  if (error !== null && forest === null) {
    return (
      <ErrorBanner
        error={error}
        onRetry={refetch}
        onHome={() => navigate("/")}
      />
    );
  }
  if (loading || forest === null || model === null) return <Loading />;
  if (legacyFocusProbeKey) {
    if (
      legacyFocusProbe?.key !== legacyFocusProbeKey ||
      legacyFocusProbe.loading
    ) {
      return <Loading />;
    }
    if (legacyFocusProbe.kind === "blocked" && focusRunId) {
      return <BlockedRunNotice projectRoot={projectRoot} runId={focusRunId} />;
    }
  }
  // Legacy target (no node identity) → fall back to the legacy per-run
  // workbench. Project forests normally omit legacy runs, but legacy-shaped
  // forest fixtures and a positive deep-link probe both land here.
  if (forest.legacy && focusRunId) {
    return (
      <LegacyGraphWorkbench
        projectRoot={projectRoot}
        runId={focusRunId}
        onOpenSettings={() => setSettingsOpen(true)}
      />
    );
  }
  if (legacyFocusProbeKey) {
    if (legacyFocusProbe?.kind === "legacy" && focusRunId) {
      return (
        <LegacyGraphWorkbench
          projectRoot={projectRoot}
          runId={focusRunId}
          onOpenSettings={() => setSettingsOpen(true)}
        />
      );
    }
  }
  // Zero-head project (and no focus run) → empty canvas. familyCount>0 means
  // all known runs predate the lineage index, so the empty state must be
  // honest instead of claiming the project has no data.
  const draftOnlyRunId =
    model.nodes.find((node) => node.isDraft)?.draftId ?? null;
  const shellRunId =
    resolvedRunId ?? (draftOnlyRunId ? `draft:${draftOnlyRunId}` : null);

  const effectiveActiveRunId =
    activeRunId ??
    forest.heads.find((h) => h.runId === resolvedRunId)?.runId ??
    newestHeadRunId ??
    shellRunId ??
    "";

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

  const handleRunDeleted = (deletedRunId: string) => {
    const fallbackRunId = forest.heads.find(
      (head) => head.runId !== deletedRunId,
    )?.runId ?? null;
    setActiveRunId((current) =>
      current === deletedRunId ? fallbackRunId : current,
    );
    setRailRefreshToken((token) => token + 1);
    void refetch();
  };

  const handleExecuteDraft = async (draftId: string) => {
    const entry = registry.get(draftId);
    if (!entry) return;
    setDraftBusy(true);
    dispatchDraft({ type: "executing", draftId });
    try {
      const executionMode =
        entry.draft?.default_execution_mode ??
        entry.validation?.validated_execution_mode ??
        "rerun_child";
      const result = await executePipelineDraft(projectRoot, draftId, {
        validated_draft_hash: entry.validation?.validated_draft_hash ?? entry.draftHash,
        execution_mode: executionMode,
      });
      const provenance = entry.draft?.notebook_provenance;
      if (provenance?.notebook_id && provenance.option_id) {
        // The Graph editor is another execution surface for a Notebook Draft.
        // Reconcile only after the real run reaches a terminal state; otherwise
        // Notebook could advance its active head on a merely-dispatched run.
        void waitForRunTerminal(projectRoot, result.run_id).then((detail) => {
          if (!detail) return;
          const succeeded = detail.status === "completed";
          return completeNotebookOptionExecution(
            projectRoot,
            provenance.notebook_id,
            provenance.option_id,
            {
              execution_status: succeeded ? "succeeded" : "failed",
              run_id: result.run_id,
              ...(succeeded
                ? {}
                : {
                    error_code:
                      detail.errors?.issues?.[0]?.code ?? "WORKFLOW_NOT_COMPLETED",
                  }),
            },
          );
        }).catch(() => {
          // The Run remains authoritative; a remounted Notebook can retry the
          // reconciliation from the persisted Draft provenance.
        });
      }
      if (executionMode === "genesis") {
        handleGenesisDraftExecuted(result, draftId);
        return;
      }
      // v1.6.9 B1 — the produced run is a background async job; it is NOT in the
      // forest yet (a long run indexes minutes later). So keep the draft node on
      // the canvas in its "executing" (pending) state — the `executing` dispatch
      // above already set it — and hand off to the index-wait layer. Capture the
      // focus target now (the forest has no produced node to focus yet) for
      // onIndexed to consume. Everything the old success branch did inline —
      // activate the run, set pending focus, remove the draft, delete the
      // persisted draft — moves to onIndexed, gated on the run actually
      // indexing. The old immediate `void refetch()` is dropped: usePendingRun
      // owns refetching (it refetches every poll tick until the run indexes).
      pendingRerunFocus.current = {
        forest_node_key: null,
        op_node_id:
          result.focus.poll?.rerun_from_op_node_id ??
          result.produced_lineage.rerun_from_op_node_id ??
          entry.sourceOpNodeId ??
          "",
        node_hash: null,
      };
      setPendingRerunRun({ runId: result.focus.run_id, draftId, attempts: 0 });
    } catch (e) {
      dispatchDraft({ type: "failed", draftId });
      console.error("draft execute failed", e);
    } finally {
      setDraftBusy(false);
    }
  };

  const handleGenesisDraftExecuted = (
    result: DraftExecutionResult,
    draftId: string,
  ) => {
    setActiveRunId(result.focus.run_id);
    setPendingGenesisRun({
      runId: result.focus.run_id,
      draftId,
      attempts: 0,
    });
    void refetch();
  };

  const genesisWizardDrawer = genesisWizardOpen ? (
    <aside
      data-testid="genesis-wizard-drawer"
      style={{
        position: "absolute",
        top: 0,
        right: 0,
        bottom: 0,
        width: 460,
        borderLeft: "1px solid var(--separator)",
        padding: 22,
        overflowY: "auto",
        background: "var(--bg-canvas)",
        boxShadow: "-12px 0 24px rgba(0, 0, 0, 0.22)",
        zIndex: 10,
      }}
    >
      <GenesisWizard
        projectRoot={projectRoot}
        onClose={closeGenesisWizard}
        onDraftUpdated={draftHandlers.onGenesisDraftUpdated}
        onDraftValidated={draftHandlers.onGenesisDraftValidated}
        onDraftExecuting={draftHandlers.onGenesisDraftExecuting}
        onDraftFailed={draftHandlers.onGenesisDraftFailed}
        onDraftExecuted={handleGenesisDraftExecuted}
      />
    </aside>
  ) : null;

  const notebookActiveRunId = forest.heads.some((head) => head.runId === effectiveActiveRunId)
    ? effectiveActiveRunId
    : null;
  const selectedView = searchParams.get("view");
  const waitForPersistedGenesisDrafts =
    !shellRunId &&
    forest.heads.length === 0 &&
    !draftHandlers.persistedDraftsHydrated &&
    selectedView !== "notebook" &&
    selectedView !== "home";
  const body = waitForPersistedGenesisDrafts ? (
    <Loading />
  ) : !shellRunId && selectedView === "notebook" ? (
    <NotebookOnlyShell
      projectRoot={projectRoot}
      activeRunId={notebookActiveRunId}
      onOpenMemorySettings={() => setSettingsOpen(true)}
      onMaterializedDraft={(response) => {
        draftHandlers.onForkDraft(response);
        void refetch();
      }}
    />
  ) : !shellRunId && selectedView === "home" ? (
    <HomeOnlyShell
      projectRoot={projectRoot}
      onOpenSettings={() => setSettingsOpen(true)}
    />
  ) : !shellRunId ? (
    <EmptyProjectCanvas
      projectRoot={projectRoot}
      legacyFamilyCount={forest.familyCount}
      legacyRunCount={forest.familyRunCount}
      onOpenWizard={() => setGenesisWizardOpen(true)}
    />
  ) : (
    <RerunProvider projectRoot={projectRoot} runId={effectiveActiveRunId} onRerun={handleRerun}>
      <ForestContext.Provider
        value={{
          forest,
          activeRunId: effectiveActiveRunId,
          setActiveRunId,
          refetch: () => void refetch(),
          onRunDeleted: handleRunDeleted,
        }}
      >
        <WorkbenchStateProvider runId={shellRunId} validNodeKeys={validNodeKeys}>
          <DraftActionsProvider
            value={{
              registry,
              busy: draftBusy,
              errors: draftHandlers.errors,
              onForkDraft: draftHandlers.onForkDraft,
              onPatch: draftHandlers.onPatch,
              onValidate: draftHandlers.onValidate,
              onExecute: handleExecuteDraft,
              onDiscard: draftHandlers.onDiscard,
              onEnsureLoaded: draftHandlers.onEnsureLoaded,
            }}
          >
            <LineageBridge model={model}>
              <CompareProvider>
                <AgentSurfaceProvider projectRoot={projectRoot} runId={shellRunId}>
                  <ReportWorkspaceProvider projectRoot={projectRoot}>
                    <WorkbenchShell
                      runId={shellRunId}
                      projectRoot={projectRoot}
                      onResumeGenesisDraft={
                        draftOnlyRunId ? () => setGenesisWizardOpen(true) : undefined
                      }
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
                      onOpenSettings={() => setSettingsOpen(true)}
                    />
                  </ReportWorkspaceProvider>
                </AgentSurfaceProvider>
              </CompareProvider>
            </LineageBridge>
          </DraftActionsProvider>
        </WorkbenchStateProvider>
      </ForestContext.Provider>
    </RerunProvider>
  );

  return (
    <div style={{ position: "relative", height: "100%", minHeight: 0, overflow: "hidden" }}>
      <ProjectRootProvider projectRoot={projectRoot}>
        <RailRefreshContext.Provider value={railRefreshToken}>
          {body}
        </RailRefreshContext.Provider>
        {genesisWizardDrawer}
      </ProjectRootProvider>
    </div>
  );
}

function HomeOnlyShell({
  projectRoot,
  onOpenSettings,
}: {
  projectRoot: string;
  onOpenSettings: () => void;
}) {
  const navigate = useNavigate();

  return (
    <div
      data-testid="workbench-home-shell"
      style={{ display: "flex", flexDirection: "column", height: "100%", minHeight: 0 }}
    >
      <div
        role="toolbar"
        aria-label="Project toolbar"
        style={{ display: "flex", alignItems: "center", gap: 10, padding: "0 16px", height: 40, borderBottom: "1px solid var(--separator, #2e2e30)" }}
      >
        <ProjectSwitcher projectRoot={projectRoot} />
        <span style={{ color: "var(--label-secondary)", fontSize: 12 }}>Home</span>
        <button
          type="button"
          data-testid="workbench-home-graph"
          onClick={() => navigate(window.location.pathname)}
          style={{ marginLeft: "auto", padding: "4px 10px", borderRadius: 6, border: "1px solid var(--separator)", background: "transparent", color: "var(--label)", cursor: "pointer", fontSize: 12 }}
        >
          Graph
        </button>
        <button
          type="button"
          data-testid="workbench-home-shell-settings"
          onClick={onOpenSettings}
          style={{ padding: "4px 10px", borderRadius: 6, border: "1px solid var(--separator)", background: "transparent", color: "var(--label)", cursor: "pointer", fontSize: 12 }}
        >
          Settings
        </button>
      </div>
      <div style={{ flex: 1, minHeight: 0, overflow: "hidden" }}>
        <WorkbenchHomeView
          projectRoot={projectRoot}
          onOpenSettings={onOpenSettings}
          onOpenProject={(root) => navigate(`/p/${rootToSlug(root)}/graph`)}
        />
      </div>
    </div>
  );
}

function NotebookOnlyShell({
  projectRoot,
  activeRunId,
  onOpenMemorySettings,
  onMaterializedDraft,
}: {
  projectRoot: string;
  activeRunId: string | null;
  onOpenMemorySettings: () => void;
  onMaterializedDraft: (response: NotebookMaterializationResponse) => void;
}) {
  const navigate = useNavigate();

  return (
    <div
      data-testid="workbench-notebook-shell"
      style={{ display: "flex", flexDirection: "column", height: "100%", minHeight: 0 }}
    >
      <div
        role="toolbar"
        aria-label="Project toolbar"
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          padding: "0 16px",
          height: 40,
          borderBottom: "1px solid var(--separator, #2e2e30)",
        }}
      >
        <ProjectSwitcher projectRoot={projectRoot} />
        <span style={{ color: "var(--label-secondary)", fontSize: 12 }}>Notebook</span>
        <button
          type="button"
          data-testid="workbench-notebook-graph"
          onClick={() => navigate(window.location.pathname)}
          style={{
            marginLeft: "auto",
            padding: "4px 10px",
            borderRadius: 6,
            border: "1px solid var(--separator)",
            background: "transparent",
            color: "var(--label)",
            cursor: "pointer",
            fontSize: 12,
          }}
        >
          Graph
        </button>
      </div>
      <NotebookRouteView
        projectRoot={projectRoot}
        activeRunId={activeRunId}
        onOpenMemorySettings={onOpenMemorySettings}
        onMaterializedDraft={onMaterializedDraft}
      />
    </div>
  );
}

/**
 * v1.6.8 T11 — the empty-canvas state for a zero-run project. Dark canvas
 * surface consistent with the workbench shell, a centered empty-state card
 * with the genesis CTA. The topbar row keeps the project switcher reachable
 * even before any run exists.
 */
function EmptyProjectCanvas({
  projectRoot,
  legacyFamilyCount = 0,
  legacyRunCount = 0,
  onOpenWizard,
}: {
  projectRoot: string;
  legacyFamilyCount?: number;
  legacyRunCount?: number;
  onOpenWizard: () => void;
}) {
  const navigate = useNavigate();
  const hasLegacyFamilies = legacyFamilyCount > 0;
  const legacyDisplayRunCount =
    legacyRunCount > 0 ? legacyRunCount : legacyFamilyCount;
  return (
    <div
      data-testid="workbench-empty-canvas"
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100%",
        minHeight: 0,
      }}
    >
      <div
        role="toolbar"
        aria-label="Project toolbar"
        style={{
          display: "flex",
          alignItems: "center",
          gap: 16,
          padding: "0 16px",
          height: 40,
          borderBottom: "1px solid var(--separator, #2e2e30)",
          background: "var(--surface-elevated, transparent)",
        }}
      >
          <ProjectSwitcher projectRoot={projectRoot} />
          <button
            type="button"
            data-testid="notebook-cta"
            onClick={() => navigate(`${window.location.pathname}?view=notebook`)}
            style={{
              padding: "4px 10px",
              borderRadius: 6,
              border: "1px solid var(--separator)",
              background: "transparent",
              color: "var(--label)",
              cursor: "pointer",
              fontSize: 12,
            }}
          >
            Notebook
          </button>
      </div>
      <div style={{ display: "flex", flexDirection: "row", flex: 1, minHeight: 0 }}>
        <div
          style={{
            flex: 1,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            background: "var(--bg-canvas)",
          }}
        >
          <div
            style={{
              textAlign: "center",
              padding: "28px 36px",
              borderRadius: 12,
              background: "var(--bg-card-2)",
              boxShadow: "0 0 0 1px var(--separator)",
            }}
          >
            <p style={{ margin: "0 0 6px", fontSize: 15, color: "var(--label)" }}>
              {hasLegacyFamilies
                ? `This project has ${legacyDisplayRunCount} run${legacyDisplayRunCount === 1 ? "" : "s"} from before lineage indexing; they cannot be shown in the graph.`
                : "This project has no imported data or analysis yet."}
            </p>
            {hasLegacyFamilies && (
              <p
                style={{
                  margin: "0 0 10px",
                  fontSize: 12,
                  color: "var(--label-secondary)",
                }}
              >
                Open the run details page (?tab=overview) to view legacy results.
              </p>
            )}
            <p
              className="mono"
              style={{
                margin: "0 0 16px",
                fontSize: 12,
                color: "var(--label-tertiary)",
              }}
            >
              {projectRoot}
            </p>
            <button
              type="button"
              data-testid="genesis-cta"
              onClick={onOpenWizard}
              style={{
                padding: "8px 18px",
                borderRadius: 8,
                border: 0,
                background: "var(--tint, #0a84ff)",
                color: "#fff",
                fontSize: 13,
                fontWeight: 600,
                cursor: "pointer",
              }}
            >
              ＋ Import data and create analysis
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function BlockedRunNotice({
  projectRoot,
  runId,
}: {
  projectRoot: string;
  runId: string;
}) {
  return (
    <div
      data-testid="blocked-run-notice"
      style={{
        display: "grid",
        placeItems: "center",
        height: "100%",
        minHeight: 0,
        padding: 32,
        background: "var(--bg-canvas)",
      }}
    >
      <section
        style={{
          maxWidth: 560,
          padding: 24,
          border: "1px solid var(--danger, #d33)",
          borderRadius: 12,
          background: "var(--bg-card-2)",
        }}
      >
        <h1 style={{ margin: "0 0 8px", fontSize: 18 }}>Analysis blocked</h1>
        <p style={{ margin: "0 0 10px", color: "var(--label-secondary)" }}>
          This analysis was blocked before lineage was recorded.
        </p>
        <p style={{ margin: 0, color: "var(--label-secondary)", fontSize: 13 }}>
          Fix the input guardrail issue and start a new analysis; this run has no graph nodes to inspect.
        </p>
        <p className="mono" style={{ margin: "14px 0 0", fontSize: 12, color: "var(--label-tertiary)" }}>
          {projectRoot} · {runId}
        </p>
      </section>
    </div>
  );
}

function LegacyGraphWorkbench({
  projectRoot,
  runId,
  onOpenSettings,
}: WorkbenchRouteContainerProps & { onOpenSettings: () => void }) {
  const navigate = useNavigate();
  const appShellContext = useOutletContext<AppShellStatusContext>();
  const { model, loading, error, refetch } = useGraphData(projectRoot, runId);

  useEffect(() => {
    if (!appShellContext?.setError) return;
    if (error?.kind === "not_found") {
      appShellContext.setError("Project not found");
      return;
    }
    appShellContext.setError(null);
  }, [appShellContext?.setError, error]);

  const validNodeKeys = useMemo<ReadonlySet<string> | undefined>(() => {
    if (model === null) return undefined;
    return new Set(model.nodes.map((n) => n.nodeKey));
  }, [model]);

  if (loading) return <Loading />;
  if (error !== null) {
    return (
      <ErrorBanner
        error={error}
        onRetry={refetch}
        onHome={() => navigate("/")}
      />
    );
  }
  if (model === null) return <Loading />;

  return (
    <WorkbenchStateProvider runId={runId} validNodeKeys={validNodeKeys}>
      <LineageBridge model={model}>
        <AgentSurfaceProvider projectRoot={projectRoot} runId={runId}>
          <ReportWorkspaceProvider projectRoot={projectRoot}>
            <WorkbenchShell
              runId={runId}
              projectRoot={projectRoot}
              onOpenSettings={onOpenSettings}
            />
          </ReportWorkspaceProvider>
        </AgentSurfaceProvider>
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
  onResumeGenesisDraft,
  pendingFocusTarget = null,
  onPendingFocusConsumed,
  onPendingFocusRetry,
  onOpenSettings,
}: {
  runId: string;
  projectRoot: string;
  onResumeGenesisDraft?: () => void;
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
  const [runHistoryOpen, setRunHistoryOpen] = useState(() => readRunHistoryOpen(projectRoot));
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
    setRunHistoryOpen(readRunHistoryOpen(projectRoot));
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

  const onRunHistoryOpenChange = useCallback((open: boolean) => {
    persistRunHistoryOpen(projectRoot, open);
    setRunHistoryOpen(open);
  }, [projectRoot]);

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
    const width = Math.min(
      Math.max(360, window.innerWidth - 16),
      Math.max(360, resize.startWidth + (growsLeft ? -deltaX : deltaX)),
    );
    const height = Math.min(
      Math.max(280, window.innerHeight - 56),
      Math.max(280, resize.startHeight + (growsTop ? -deltaY : deltaY)),
    );
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
      setNavigationParams(applyAgentNavigationRef(navigationParams, ref));
      return true;
    },
    [navigationParams, setNavigationParams],
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
          {!nodePanelCollapsed && (['top-left', 'top-right', 'bottom-left', 'bottom-right'] as ResizeCorner[]).map((corner) => (
            <button
              key={corner}
              type="button"
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

  return (
    <div
      data-testid="workbench-route"
      className="workbench-route"
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100%",
        minHeight: 0,
        overflow: "hidden",
      }}
    >
      <WorkbenchTopbar
        projectRoot={projectRoot}
        leadingActions={
          state.view !== "home" ? (
            <button
              type="button"
              data-testid="run-history-toggle"
              aria-label={runHistoryOpen ? "Hide run history" : "Show run history"}
              title={runHistoryOpen ? "Hide runs" : "Show runs"}
              onClick={() => onRunHistoryOpenChange(!runHistoryOpen)}
              style={{
                alignItems: "center",
                display: "inline-flex",
                height: 28,
                justifyContent: "center",
                padding: 4,
                width: 28,
                border: 0,
                borderRadius: 6,
                background: "transparent",
                color: "var(--label-secondary)",
                cursor: "pointer",
                fontSize: 12,
              }}
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                <rect x="3" y="4" width="18" height="16" rx="2.5" stroke="currentColor" strokeWidth="1.6" />
                <line x1="9" y1="4" x2="9" y2="20" stroke="currentColor" strokeWidth="1.6" />
              </svg>
            </button>
          ) : null
        }
        extraActions={
          onResumeGenesisDraft ? (
            <button
              type="button"
              data-testid="genesis-resume-cta"
              onClick={onResumeGenesisDraft}
              style={{
                padding: "4px 10px",
                borderRadius: 6,
                border: 0,
                background: "var(--tint-bg, rgba(10,132,255,0.12))",
                color: "var(--tint, #0a84ff)",
                cursor: "pointer",
                fontSize: 12,
              }}
            >
              Resume new analysis
            </button>
          ) : null
        }
      />
      <AgentNavigationContext.Provider value={openAgentNavigation}>
        <div
          data-testid="workbench-main-row"
          style={{
            display: "flex",
            flexDirection: "row",
            flex: 1,
            minHeight: 0,
            minWidth: 0,
            overflow: "hidden",
          }}
        >
          {state.view !== "home" && (
            <RunHistoryRail
              projectRoot={projectRoot}
              open={runHistoryOpen}
              onOpenChange={onRunHistoryOpenChange}
            />
          )}
          <div
                data-testid="workbench-center-column"
                style={{
                  display: "flex",
                  flexDirection: "column",
                  flex: 1,
                  minHeight: 0,
                  minWidth: 0,
                  overflow: "hidden",
                }}
              >
                <WorkbenchMain
                  projectRoot={projectRoot}
                  reportFocusRequest={reportFocusRequest}
                  onOpenSettings={onOpenSettings}
                  onOpenProject={(root) => {
                    navigate(`/p/${rootToSlug(root)}/graph`);
                  }}
                />
                {state.view !== "home" && (
                  <BottomPanel runId={runId} projectRoot={projectRoot} />
                )}
              </div>
              {state.view !== "home" && (
                <PanelHost
                  projectRoot={projectRoot}
                  collapseLabel={reportReviewTabActive ? "report review" : "node panel"}
                  activeKind={
                    reportReviewLayout === "docked" && reportReviewTabActive
                      ? "report-review"
                      : nodePanelTabActive && nodePanelLayout === "docked"
                        ? "node"
                        : null
                  }
                  collapsed={reportReviewTabActive && reportReviewLayout === "docked"
                    ? reportReviewCollapsed
                    : nodePanelTabActive && nodePanelLayout === "docked"
                      ? nodePanelCollapsed
                      : undefined}
                  onCollapsedChange={reportReviewTabActive && reportReviewLayout === "docked"
                    ? (collapsed) => setReportReviewUi((current) => ({ ...current, collapsed }))
                    : nodePanelTabActive && nodePanelLayout === "docked"
                      ? (collapsed) => setNodePanelUi((current) => ({ ...current, collapsed }))
                      : undefined}
                  tabs={
                    <DetailDrawerTabs
                      tabs={dockedTabs}
                      nodes={model.nodes}
                      activeTabId={dockedActiveTabId}
                      onActive={dispatch.selectByTabSwitch}
                      onClose={dispatch.closeTab}
                      lastEvictedTabId={state.lastEvictedTabId}
                    />
                  }
                  nodePanel={nodePanelLayout === "docked" ? nodePanelContent : null}
                  reportPanel={reportReviewLayout === "docked" ? reportReviewPanel : null}
                />
              )}
        </div>
      </AgentNavigationContext.Provider>
      {state.view !== "home" && <ContextMenu />}
      {state.view !== "home" && <SearchPalette />}
      {state.view !== "home" && <CommandPalette projectRoot={projectRoot} />}
      {state.view !== "home" && (
        <RawJsonModal
          open={rawJsonOpen}
          onClose={() => setRawJsonOpen(false)}
          node={selectedNode}
        />
      )}
      {reportReviewFloating}
      {nodePanelFloating}
    </div>
  );
}
