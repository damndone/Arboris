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

import { useEffect, useMemo, useReducer, useRef, useState } from "react";
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
import { RawJsonModal } from "../lineage/modals/RawJsonModal";
import { RunHistoryRail } from "../lineage/runRail/RunHistoryRail";
import "../lineage/tokens/lineage.css";
import { WorkbenchStateProvider } from "./WorkbenchStateProvider";
import { useWorkbench } from "./WorkbenchStateProvider";
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
  legacy: boolean;
};

const PENDING_FOCUS_RETRY_LIMIT = 20;
const PENDING_FOCUS_RETRY_DELAY_MS = 200;

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
}

type AppShellStatusContext = {
  setError?: (message: string | null) => void;
};

/** v1.6.8 T11 — the project-keyed workbench home. The forest is keyed by
 *  projectRoot alone; runId is only an optional focus hint. */
export function WorkbenchHome({ projectRoot, focusRunId }: WorkbenchHomeProps) {
  // This is the live project-home mount path. The bootstrap itself is
  // idempotent so React StrictMode and route remounts cannot duplicate a view.
  useEffect(() => {
    registerBuiltinFeatureViews();
  }, []);

  // v1.6.8 — the project home renders the project forest. A run deep link is
  // only a focus hint; if that run is absent from the project forest, probe the
  // old run-keyed headset once so true legacy runs can still use the legacy
  // per-run workbench.
  return <ForestWorkbench projectRoot={projectRoot} focusRunId={focusRunId} />;
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

function ForestWorkbench({ projectRoot, focusRunId }: WorkbenchHomeProps) {
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
  const [genesisWizardOpen, setGenesisWizardOpen] = useState(false);
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
    if (searchParams.get("genesis") !== "1") return;
    setGenesisWizardOpen(true);
    const next = new URLSearchParams(searchParams);
    next.delete("genesis");
    setSearchParams(next, { replace: true });
  }, [searchParams, setSearchParams]);

  const legacyFocusProbeKey =
    forest && !forest.legacy && focusRunId && !focusRunIsKnownHead
      ? `${projectRoot}\u0000${focusRunId}`
      : null;

  useEffect(() => {
    if (!legacyFocusProbeKey || !focusRunId) {
      return undefined;
    }
    let cancelled = false;
    setLegacyFocusProbe({ key: legacyFocusProbeKey, loading: true, legacy: false });
    getRunGraphHeadSet(projectRoot, focusRunId)
      .then((raw) => {
        if (cancelled) return;
        setLegacyFocusProbe({
          key: legacyFocusProbeKey,
          loading: false,
          legacy: raw.legacy === true || !Array.isArray(raw.heads),
        });
      })
      .catch(() => {
        if (cancelled) return;
        setLegacyFocusProbe({
          key: legacyFocusProbeKey,
          loading: false,
          legacy: false,
        });
      });
    return () => {
      cancelled = true;
    };
  }, [focusRunId, legacyFocusProbeKey, projectRoot]);

  const model = useMemo(
    () => {
      const base = forest
        ? forestToGraphViewModel(forest, resolvedRunId ?? "")
        : null;
      return base ? mergeDraftsIntoModel(base, registry) : null;
    },
    [forest, resolvedRunId, registry],
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
  // Legacy target (no node identity) → fall back to the legacy per-run
  // workbench. Project forests normally omit legacy runs, but legacy-shaped
  // forest fixtures and a positive deep-link probe both land here.
  if (forest.legacy && focusRunId) {
    return <LegacyGraphWorkbench projectRoot={projectRoot} runId={focusRunId} />;
  }
  if (legacyFocusProbeKey) {
    if (
      legacyFocusProbe?.key !== legacyFocusProbeKey ||
      legacyFocusProbe.loading
    ) {
      return <Loading />;
    }
    if (legacyFocusProbe.legacy && focusRunId) {
      return <LegacyGraphWorkbench projectRoot={projectRoot} runId={focusRunId} />;
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
        onClose={() => setGenesisWizardOpen(false)}
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
  const body = !shellRunId && searchParams.get("view") === "notebook" ? (
    <NotebookOnlyShell
      projectRoot={projectRoot}
      activeRunId={notebookActiveRunId}
      onMaterializedDraft={(response) => {
        draftHandlers.onForkDraft(response);
        void refetch();
      }}
    />
  ) : !shellRunId && searchParams.get("view") === "home" ? (
    <HomeOnlyShell projectRoot={projectRoot} />
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
              />
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

function HomeOnlyShell({ projectRoot }: { projectRoot: string }) {
  const navigate = useNavigate();
  const [settingsOpen, setSettingsOpen] = useState(false);

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
          onClick={() => setSettingsOpen(true)}
          style={{ padding: "4px 10px", borderRadius: 6, border: "1px solid var(--separator)", background: "transparent", color: "var(--label)", cursor: "pointer", fontSize: 12 }}
        >
          Settings
        </button>
      </div>
      <div style={{ flex: 1, minHeight: 0, overflow: "hidden" }}>
        {settingsOpen ? (
          <LlmProviderManager onBack={() => setSettingsOpen(false)} />
        ) : (
          <WorkbenchHomeView
            projectRoot={projectRoot}
            onOpenSettings={() => setSettingsOpen(true)}
            onOpenProject={(root) => navigate(`/p/${rootToSlug(root)}/graph`)}
          />
        )}
      </div>
    </div>
  );
}

function NotebookOnlyShell({
  projectRoot,
  activeRunId,
  onMaterializedDraft,
}: {
  projectRoot: string;
  activeRunId: string | null;
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
                : "This project has no data yet."}
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
              ＋ New analysis
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function LegacyGraphWorkbench({
  projectRoot,
  runId,
}: WorkbenchRouteContainerProps) {
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
  onResumeGenesisDraft,
  pendingFocusTarget = null,
  onPendingFocusConsumed,
  onPendingFocusRetry,
}: {
  runId: string;
  projectRoot: string;
  onResumeGenesisDraft?: () => void;
  pendingFocusTarget?: PendingFocusTarget | null;
  onPendingFocusConsumed?: () => void;
  onPendingFocusRetry?: () => void;
}) {
  const { model, selectedKey, select } = useLineage();
  const { state } = useWorkbench();
  const location = useLocation();
  const navigate = useNavigate();
  const [navigationParams, setNavigationParams] = useSearchParams();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [rawJsonOpen, setRawJsonOpen] = useState(false);
  const settingsLocationInitialized = useRef(false);

  const openAgentNavigation = useMemo(
    () => (ref: Parameters<typeof applyAgentNavigationRef>[1]) => {
      if (!ref.available) return false;
      setNavigationParams(applyAgentNavigationRef(navigationParams, ref));
      return true;
    },
    [navigationParams, setNavigationParams],
  );

  useEffect(() => {
    if (!settingsLocationInitialized.current) {
      settingsLocationInitialized.current = true;
      return;
    }
    setSettingsOpen(false);
  }, [location.pathname, location.search]);

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
    enabled: state.view !== "home" && !settingsOpen,
  });

  // F6: global action-registry shortcut dispatcher (e.g. ⌘⇧C copy id).
  // Reuses F4's editable-target guard; acts on the selected node.
  useGlobalShortcuts({ enabled: state.view !== "home" && !settingsOpen });

  return (
    <div
      data-testid="workbench-route"
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
        onOpenSettings={() => setSettingsOpen(true)}
        onViewChange={() => setSettingsOpen(false)}
        extraActions={
          onResumeGenesisDraft ? (
            <button
              type="button"
              data-testid="genesis-resume-cta"
              onClick={onResumeGenesisDraft}
              style={{
                padding: "4px 10px",
                borderRadius: 6,
                border: "1px solid var(--separator)",
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
            overflow: "hidden",
          }}
        >
          {state.view !== "home" && <RunHistoryRail projectRoot={projectRoot} />}
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
            {settingsOpen ? (
              <LlmProviderManager onBack={() => setSettingsOpen(false)} />
            ) : (
              <AgentSurfaceProvider projectRoot={projectRoot} runId={runId}>
                <WorkbenchMain
                  projectRoot={projectRoot}
                  onOpenSettings={() => setSettingsOpen(true)}
                  onOpenProject={(root) => {
                    navigate(`/p/${rootToSlug(root)}/graph`);
                  }}
                />
                {!settingsOpen && state.view !== "home" && (
                  <BottomPanel runId={runId} projectRoot={projectRoot} />
                )}
              </AgentSurfaceProvider>
            )}
          </div>
          {!settingsOpen && state.view !== "home" && selectedNode !== null && (
            <DetailDrawer
              node={selectedNode}
              projectRoot={projectRoot}
              onClose={() => select(null)}
              onShowJson={() => setRawJsonOpen(true)}
            />
          )}
        </div>
      </AgentNavigationContext.Provider>
      {!settingsOpen && state.view !== "home" && <ContextMenu />}
      {!settingsOpen && state.view !== "home" && <SearchPalette />}
      {!settingsOpen && state.view !== "home" && <CommandPalette projectRoot={projectRoot} />}
      {!settingsOpen && state.view !== "home" && (
        <RawJsonModal
          open={rawJsonOpen}
          onClose={() => setRawJsonOpen(false)}
          node={selectedNode}
        />
      )}
    </div>
  );
}
