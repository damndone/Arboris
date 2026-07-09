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
import { ProjectSwitcher, WorkbenchTopbar } from "./WorkbenchTopbar";
import { WorkbenchMain } from "./WorkbenchMain";
import { ContextMenu } from "./ContextMenu";
import { useGlobalShortcuts } from "./useGlobalShortcuts";
import { BottomPanel } from "./BottomPanel";
import { SearchPalette } from "./SearchPalette";
import { CommandPalette } from "./CommandPalette";
import { ProjectRootProvider } from "./ProjectRootContext";
import { useForestData } from "../lineage/hooks/useForestData";
import { forestToGraphViewModel } from "./forestModel";
import { ForestContext } from "./ForestContext";
import { RerunProvider } from "../lineage/detail/RerunContext";
import { draftReducer, emptyRegistry } from "../lineage/drafts/draftRegistry";
import { mergeDraftsIntoModel } from "../lineage/drafts/mergeDraftsIntoModel";
import { DraftActionsProvider } from "../lineage/drafts/DraftActionsContext";
import { GenesisWizard } from "../lineage/drafts/GenesisWizard";
import {
  listPipelineDrafts,
  getRunGraphHeadSet,
  getPipelineDraft,
  validatePipelineDraft,
  executePipelineDraft,
  patchPipelineDraftParams,
  deletePipelineDraft,
  type RerunResponseV1,
  type PipelineDraftResponse,
  type PipelineDraftPatchRequest,
  type DraftExecutionResult,
  type DraftValidationResult,
} from "../api";
import type { GraphViewNode, HeadSetNode } from "../lineage/api/graphViewTypes";
import { usePendingRun, type PendingRun } from "./usePendingRun";

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

interface WorkbenchHomeProps {
  projectRoot: string;
  /** Optional run deep link (?run=). Absent → newest head is the active run;
   *  a zero-run project renders the empty canvas + genesis CTA instead. */
  focusRunId?: string;
}

/** v1.6.8 T11 — the project-keyed workbench home. The forest is keyed by
 *  projectRoot alone; runId is only an optional focus hint. */
export function WorkbenchHome({ projectRoot, focusRunId }: WorkbenchHomeProps) {
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
  const { forest, loading, error, refetch } = useForestData(projectRoot);
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [pendingFocusTarget, setPendingFocusTarget] =
    useState<PendingFocusTarget | null>(null);
  const [legacyFocusProbe, setLegacyFocusProbe] =
    useState<LegacyFocusProbe | null>(null);
  const [genesisWizardOpen, setGenesisWizardOpen] = useState(false);
  const [pendingGenesisRun, setPendingGenesisRun] =
    useState<PendingRun | null>(null);
  const initializedPendingQueryKey = useRef<string | null>(null);
  const [registry, dispatchDraft] = useReducer(draftReducer, undefined, emptyRegistry);
  const [draftBusy, setDraftBusy] = useState(false);
  const focusRunIsKnownHead = useMemo(
    () => Boolean(focusRunId && forest?.heads.some((h) => h.runId === focusRunId)),
    [forest, focusRunId],
  );

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

  // Hydrate persisted (unexecuted) drafts onto the forest on mount so drafts
  // survive a page reload. Best-effort: never block the forest if it fails.
  useEffect(() => {
    let cancelled = false;
    listPipelineDrafts(projectRoot)
      .then(async (summaries) => {
        if (cancelled) return;
        const unexecuted = summaries.filter((s) => s.status !== "executed");
        if (unexecuted.length) {
          dispatchDraft({ type: "hydrate", summaries: unexecuted });
        }
        const unanchored = unexecuted.filter(
          (s) => !s.source_node_hash && !s.source_op_node_id,
        );
        if (unanchored.length === 0) return;
        const loaded = await Promise.allSettled(
          unanchored.map((s) => getPipelineDraft(projectRoot, s.draft_id)),
        );
        if (cancelled) return;
        for (const res of loaded) {
          if (res.status !== "fulfilled") continue;
          dispatchDraft({
            type: "put",
            draftId: res.value.draft.draft_id,
            draft: res.value.draft,
            draftHash: res.value.draft_hash,
          });
        }
      })
      .catch(() => {
        /* drafts are best-effort; never block the forest */
      });
    return () => {
      cancelled = true;
    };
  }, [projectRoot]);

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
    },
    onFailed: (draftId) => {
      dispatchDraft({ type: "failed", draftId });
    },
    setPending: setPendingGenesisRun,
  });

  if (error !== null && forest === null) {
    return <ErrorBanner error={error} onRetry={refetch} />;
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

  const handleForkDraft = (created: PipelineDraftResponse) => {
    dispatchDraft({
      type: "put",
      draftId: created.draft.draft_id,
      draft: created.draft,
      draftHash: created.draft_hash,
    });
  };

  const handlePatchDraft = async (
    draftId: string,
    body: PipelineDraftPatchRequest,
  ) => {
    setDraftBusy(true);
    try {
      const res = await patchPipelineDraftParams(projectRoot, draftId, body);
      dispatchDraft({ type: "patch", draftId, draft: res.draft, draftHash: res.draft_hash });
    } catch (e) {
      console.error("draft patch failed", e);
    } finally {
      setDraftBusy(false);
    }
  };

  const handleValidateDraft = async (draftId: string) => {
    setDraftBusy(true);
    dispatchDraft({ type: "validating", draftId });
    try {
      const v = await validatePipelineDraft(projectRoot, draftId, "rerun_child");
      dispatchDraft({
        type: "validated",
        draftId,
        validation: v,
        draftHash: v.validated_draft_hash ?? "",
      });
    } catch (e) {
      dispatchDraft({ type: "revertToDraft", draftId });
      console.error("draft validate failed", e);
    } finally {
      setDraftBusy(false);
    }
  };

  const handleExecuteDraft = async (draftId: string) => {
    const entry = registry.get(draftId);
    if (!entry) return;
    setDraftBusy(true);
    dispatchDraft({ type: "executing", draftId });
    try {
      const result = await executePipelineDraft(projectRoot, draftId, {
        validated_draft_hash: entry.validation?.validated_draft_hash ?? entry.draftHash,
        execution_mode: "rerun_child",
      });
      setActiveRunId(result.focus.run_id);
      setPendingFocusTarget({
        runId: result.focus.run_id,
        focus: {
          forest_node_key: null,
          op_node_id:
            result.focus.poll?.rerun_from_op_node_id ??
            result.produced_lineage.rerun_from_op_node_id ??
            entry.sourceOpNodeId ??
            "",
          node_hash: null,
        },
        attempts: 0,
      });
      // Execute succeeded: remove the draft node regardless of cleanup outcome.
      dispatchDraft({ type: "remove", draftId });
      void refetch();
      try {
        await deletePipelineDraft(projectRoot, draftId);
      } catch (cleanupErr) {
        console.error("draft cleanup (delete) failed post-execute", cleanupErr);
      }
    } catch (e) {
      dispatchDraft({ type: "failed", draftId });
      console.error("draft execute failed", e);
    } finally {
      setDraftBusy(false);
    }
  };

  const handleDiscardDraft = async (draftId: string) => {
    setDraftBusy(true);
    try {
      await deletePipelineDraft(projectRoot, draftId);
      dispatchDraft({ type: "remove", draftId });
    } catch (e) {
      console.error("draft discard failed", e);
    } finally {
      setDraftBusy(false);
    }
  };

  const handleEnsureDraftLoaded = async (draftId: string) => {
    const entry = registry.get(draftId);
    if (!entry || entry.draft !== null) return;
    try {
      const res = await getPipelineDraft(projectRoot, draftId);
      dispatchDraft({ type: "put", draftId, draft: res.draft, draftHash: res.draft_hash });
    } catch {
      /* best-effort; editor shows "Loading draft…" until retried */
    }
  };

  const handleGenesisDraftUpdated = (response: PipelineDraftResponse) => {
    dispatchDraft({
      type: "put",
      draftId: response.draft.draft_id,
      draft: response.draft,
      draftHash: response.draft_hash,
    });
  };

  const handleGenesisDraftValidated = (
    draftId: string,
    validation: DraftValidationResult,
  ) => {
    const entry = registry.get(draftId);
    dispatchDraft({
      type: "validated",
      draftId,
      validation,
      draftHash: validation.validated_draft_hash ?? entry?.draftHash ?? "",
    });
  };

  const handleGenesisDraftExecuting = (draftId: string) => {
    dispatchDraft({ type: "executing", draftId });
  };

  const handleGenesisDraftFailed = (draftId: string) => {
    dispatchDraft({ type: "failed", draftId });
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
        onDraftUpdated={handleGenesisDraftUpdated}
        onDraftValidated={handleGenesisDraftValidated}
        onDraftExecuting={handleGenesisDraftExecuting}
        onDraftFailed={handleGenesisDraftFailed}
        onDraftExecuted={handleGenesisDraftExecuted}
      />
    </aside>
  ) : null;

  const body = !shellRunId ? (
    <EmptyProjectCanvas
      projectRoot={projectRoot}
      legacyFamilyCount={forest.familyCount}
      legacyRunCount={forest.familyRunCount}
      onOpenWizard={() => setGenesisWizardOpen(true)}
    />
  ) : (
    <RerunProvider projectRoot={projectRoot} runId={effectiveActiveRunId} onRerun={handleRerun}>
      <ForestContext.Provider
        value={{ forest, activeRunId: effectiveActiveRunId, setActiveRunId }}
      >
        <WorkbenchStateProvider runId={shellRunId} validNodeKeys={validNodeKeys}>
          <DraftActionsProvider
            value={{
              registry,
              busy: draftBusy,
              onForkDraft: handleForkDraft,
              onPatch: handlePatchDraft,
              onValidate: handleValidateDraft,
              onExecute: handleExecuteDraft,
              onDiscard: handleDiscardDraft,
              onEnsureLoaded: handleEnsureDraftLoaded,
            }}
          >
            <LineageBridge model={model}>
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
            </LineageBridge>
          </DraftActionsProvider>
        </WorkbenchStateProvider>
      </ForestContext.Provider>
    </RerunProvider>
  );

  return (
    <div style={{ position: "relative", height: "100%", minHeight: 0, overflow: "hidden" }}>
      <ProjectRootProvider projectRoot={projectRoot}>
        {body}
        {genesisWizardDrawer}
      </ProjectRootProvider>
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
        aria-label="项目工具栏"
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
                ? `该项目的 ${legacyDisplayRunCount} 个 run 早于血缘索引，不能在图中显示`
                : "这个项目还没有数据"}
            </p>
            {hasLegacyFamilies && (
              <p
                style={{
                  margin: "0 0 10px",
                  fontSize: 12,
                  color: "var(--label-secondary)",
                }}
              >
                可通过 run 详情页（?tab=overview）查看旧结果。
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
              ＋ 新链路
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
        overflow: "hidden",
      }}
    >
      <WorkbenchTopbar
        projectRoot={projectRoot}
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
              继续新链路
            </button>
          ) : null
        }
      />
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
        <RunHistoryRail projectRoot={projectRoot} />
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
          <WorkbenchMain projectRoot={projectRoot} />
          <BottomPanel runId={runId} projectRoot={projectRoot} />
        </div>
        {selectedNode !== null && (
          <DetailDrawer
            node={selectedNode}
            projectRoot={projectRoot}
            onClose={() => select(null)}
            onShowJson={() => setRawJsonOpen(true)}
          />
        )}
      </div>
      <ContextMenu />
      <SearchPalette />
      <CommandPalette projectRoot={projectRoot} />
      <RawJsonModal
        open={rawJsonOpen}
        onClose={() => setRawJsonOpen(false)}
        node={selectedNode}
      />
    </div>
  );
}
