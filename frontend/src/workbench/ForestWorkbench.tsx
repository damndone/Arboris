import { type AppShellStatusContext, EMPTY_FOCUS, type LegacyFocusProbe, type PendingFocusTarget, type WorkbenchHomeProps } from "./workbenchPanelUi";
import "../lineage/tokens/lineage.css";
import "./panelHost.css";
import { WorkbenchShell } from "./WorkbenchShell";
import { LegacyGraphWorkbench } from "./WorkbenchRouteContainer";
import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import { useNavigate, useOutletContext, useSearchParams } from "react-router-dom";
import { ErrorBanner, Loading } from "../lineage/statusViews";
import { WorkbenchStateProvider } from "./WorkbenchStateProvider";
import { CompareProvider } from "../lineage/compare/CompareContext";
import { LineageBridge } from "./LineageBridge";
import { WorkspaceProjectStart } from "../workspace/WorkspaceProjectStart";
import { ProjectRootProvider } from "./ProjectRootContext";
import { RailRefreshContext } from "./RailRefreshContext";
import { useForestData } from "../lineage/hooks/useForestData";
import { forestToGraphViewModel } from "./forestModel";
import { ForestContext } from "./ForestContext";
import { RerunProvider, type RerunArgs, type RerunReceipt } from "../lineage/detail/RerunContext";
import { LlmProviderManager } from "../llm/LlmProviderManager";
import { draftReducer, emptyRegistry } from "../lineage/drafts/draftRegistry";
import { mergeDraftsIntoModel } from "../lineage/drafts/mergeDraftsIntoModel";
import { DraftActionsProvider } from "../lineage/drafts/DraftActionsContext";
import { GenesisWizard } from "../lineage/drafts/GenesisWizard";
import { useDraftHandlers } from "./useDraftHandlers";
import { getRunGraphHeadSet, fetchRunDetail, executePipelineDraft, deletePipelineDraft, waitForRunTerminal, type RerunResponseV1, type DraftExecutionResult } from "../api";
import { completeNotebookOptionExecution } from "../notebook/notebookApi";
import { usePendingRun, type PendingRun } from "./usePendingRun";
import { ReportWorkspaceProvider } from "../report/ReportWorkspaceContext";
// Workbench route data, providers and shared node/report window state.
// The workspace owns the only layout; legacy run URLs enter the same shell.
// Draft execution, selection, overlays and pending-index recovery remain here.


export function ForestWorkbench({
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
  const [rerunReceipt, setRerunReceipt] = useState<RerunReceipt | null>(null);
  const initializedPendingQueryKey = useRef<string | null>(null);
  const [registry, dispatchDraft] = useReducer(draftReducer, undefined, emptyRegistry);
  const [draftBusy, setDraftBusy] = useState(false);
  const runBusy = draftBusy || pendingGenesisRun !== null || pendingRerunRun !== null;
  const runBusyRef = useRef(runBusy);
  runBusyRef.current = runBusy;
  const handleRunSubmitting = (submitting: boolean) => {
    if (submitting) {
      if (runBusyRef.current) throw new Error("Another run is being submitted or observed. Open that run before submitting another.");
      runBusyRef.current = true;
    }
    setDraftBusy(submitting);
  };
  // v1.6.9 B1-4 — monotonic token handed to the RUNS rail via RailRefreshContext.
  // Bumped in the pending-run onIndexed callbacks so the rail re-fetches /runs the
  // instant a genesis / draft-execute run indexes, rather than lagging its 30s poll.
  const [railRefreshToken, setRailRefreshToken] = useState(0);
  useEffect(() => {
    // Leaving this run/project stops observation only; the submitted run remains owned by the backend.
    setPendingRerunRun(current => current?.confirmTerminal ? null : current);
    setRerunReceipt(null);
  }, [projectRoot, focusRunId]);
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

  useEffect(() => {
    const queryGenesis =
      searchParams.get("genesis") === "1" ||
      searchParams.get("open_genesis") === "1";
    if (!queryGenesis && !openGenesis && !genesisWizardOpen) {
      genesisHandoffConsumed.current = false;
    }
  }, [genesisWizardOpen, openGenesis, searchParams]);

  const openGenesisWizard = useCallback(() => {
    setGenesisWizardOpen(true);
  }, []);

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
      if (pendingGenesisRun?.draftId) {
        dispatchDraft({ type: "remove", draftId: pendingGenesisRun.draftId });
      }
      setPendingGenesisRun(null);
      closeGenesisWizard();
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
      if (pendingRerunRun?.confirmTerminal) {
        setRerunReceipt(current => current?.runId === runId ? {...current, status: "completed"} : current);
      }
      setActiveRunId(runId);
      setPendingFocusTarget({
        runId,
        focus: pendingRerunFocus.current ?? EMPTY_FOCUS,
        attempts: 0,
      });
      if (pendingRerunRun?.draftId) {
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
    onStatus: detail => {
      if (!pendingRerunRun?.confirmTerminal) return;
      const issue = detail.errors?.issues?.find(item => item.severity === "BLOCKER")
        ?? detail.errors?.issues?.[0];
      setRerunReceipt(current => current?.runId === pendingRerunRun.runId ? {
        ...current, status: detail.status === "completed" ? "indexing" : detail.status!,
        issue: issue ? `${issue.code}: ${issue.message}` : undefined,
      } : current);
      if (!["running", "queued", "cancelling", "completed"].includes(detail.status ?? "")) {
        setRailRefreshToken(token => token + 1);
      }
    },
    onUnconfirmed: message => {
      if (!pendingRerunRun?.confirmTerminal) return;
      setRerunReceipt(current => current?.runId === pendingRerunRun.runId
        ? {...current, status: "unconfirmed", issue: message} : current);
      setRailRefreshToken(token => token + 1);
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
        onHome={() => navigate("/?launcher=1")}
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

  const handleRerun = (response: RerunResponseV1, context: RerunArgs["context"]) => {
    const runId = response.run_id;
    // The project home otherwise follows the newest head before the child has finished.
    setActiveRunId(effectiveActiveRunId);
    const lineage = response.produced_lineage;
    // The server sets no focus target on a rerun (RerunSubmitted.focus is
    // always null); the produced lineage or the rerun source is the focus.
    const focus = {
      forest_node_key: null,
      op_node_id: lineage?.produced_op_node_id ?? response.rerun_from.op_node_id,
      node_hash: lineage?.produced_node_hash ?? null,
    };
    pendingRerunFocus.current = focus;
    setRerunReceipt({
      runId, contextFingerprint: context.context_fingerprint, status: "submitted",
      href: `/runs/${encodeURIComponent(runId)}?project_root=${encodeURIComponent(projectRoot)}&tab=overview`,
    });
    setPendingRerunRun({runId, attempts: 0, confirmTerminal: true});
    setRailRefreshToken(token => token + 1);
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
    if (runBusyRef.current) return;
    const entry = registry.get(draftId);
    if (!entry) return;
    runBusyRef.current = true;
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
          return completeNotebookOptionExecution(
            projectRoot,
            provenance.notebook_id,
            provenance.option_id,
            {
              run_id: result.run_id,
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
      role="dialog"
      aria-label="New analysis"
      style={{
        position: "absolute",
        top: 0,
        right: 0,
        bottom: 0,
        width: "min(460px, 100%)",
        boxSizing: "border-box",
        borderLeft: "1px solid var(--separator)",
        padding: 22,
        overflowY: "auto",
        background: "var(--bg-canvas)",
        boxShadow: "var(--shadow-pop)",
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
    selectedView !== "notebook" && selectedView !== "plans" &&
    selectedView !== "home";
  const body = waitForPersistedGenesisDrafts ? (
    <Loading />
  ) : !shellRunId ? (
    <WorkspaceProjectStart
      projectRoot={projectRoot}
      view={selectedView}
      legacyFamilyCount={forest.familyCount}
      legacyRunCount={forest.familyRunCount}
      onOpenWizard={openGenesisWizard}
      onOpenSettings={() => setSettingsOpen(true)}
      notebookActiveRunId={notebookActiveRunId}
      onMaterializedDraft={(response) => {
        draftHandlers.onForkDraft(response);
        void refetch();
      }}
    />
  ) : (
    <RerunProvider projectRoot={projectRoot} runId={effectiveActiveRunId} onRerun={handleRerun} receipt={rerunReceipt} busy={runBusy} onSubmitting={handleRunSubmitting}>
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
              busy: runBusy,
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
                  <ReportWorkspaceProvider projectRoot={projectRoot}>
                    <WorkbenchShell
                      runId={shellRunId}
                      projectRoot={projectRoot}
                      onOpenGenesisWizard={openGenesisWizard}
                      hasGenesisDraft={Boolean(draftOnlyRunId)}
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
          border: "1px solid var(--status-fails-fg)",
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

