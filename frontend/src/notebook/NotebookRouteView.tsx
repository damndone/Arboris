import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { uploadDataset } from "../api";
import {
  appendAiActivity,
  makeActivityId,
  type NotebookPlanActivityRecord,
} from "../aiActivity/aiActivityLog";

import {
  cancelNotebookPlanning,
  compileNotebookContext,
  confirmNotebookOption,
  confirmAndExecuteNotebookOption,
  ensureNotebookDatasetProjection,
  ensureNotebookProjection,
  getNotebook,
  updateNotebookFocus,
  getNotebookTrace,
  listNotebooks,
  listNotebookOptions,
  proposeNotebookOptions,
  recordNotebookDecision,
  type NotebookMaterializationResponse,
  type NotebookContextResponse,
  type NotebookInteractionMode,
  type NotebookRecord,
} from "./notebookApi";
import {
  listDomainMemoryCandidates,
  reviewDomainMemoryCandidate,
} from "./domainMemoryApi";
import { NotebookSurface } from "./NotebookSurface";
import { useAgentSurfaceOptional } from "../workbench/agent/AgentSurfaceContext";
import { useWorkbenchOptional } from "../workbench/WorkbenchStateProvider";
import { useForest } from "../workbench/ForestContext";
import { useDraftActions } from "../lineage/drafts/DraftActionsContext";
import {
  parseNotebookOptionRevision,
  parseNotebookExecutionResult,
  parseOptionExecution,
  type NotebookContextSlice,
  type NotebookData,
  type NotebookOptionRevision,
  type NotebookReadyView,
  type NotebookSelection,
  type NotebookSelectionAnchor,
  parseOptionMaterialization,
  type NotebookView,
  type OptionExecution,
  type PendingConfirmation,
  type PlanDiffLine,
  type TraceEvent,
} from "./contracts";
import type {
  DomainMemoryCandidate,
  DomainMemoryRetrievalProjection,
} from "./domainMemoryContracts";

type ApiErrorLike = Error & { code?: string | null; status?: number | null };

type NotebookPlanningResponse = Awaited<ReturnType<typeof proposeNotebookOptions>>;

interface ActivePlanningRequest {
  scopeKey: string;
  requestKey: string;
  attemptId: string;
  controller: AbortController;
  promise: Promise<NotebookPlanningResponse>;
  projectRoot: string;
  notebookId: string;
  interactionMode: NotebookInteractionMode;
  goal: string;
  activityRecorded: boolean;
  /**
   * When this planning attempt actually began, in epoch milliseconds.
   *
   * The elapsed clock has to be anchored to the attempt, not to whichever
   * component happens to be mounted. This map already outlives a remount so
   * that a re-render rejoins the in-flight request instead of starting a
   * second one; the start instant belongs at the same level, otherwise the
   * counter restarts at zero against a budget the request has been spending
   * all along, which reads as healthy when it is not.
   */
  startedAt: number;
}

const planningRequests = new Map<
  string,
  ActivePlanningRequest
>();

function proposeNotebookOptionsOnce(
  projectRoot: string,
  notebookId: string,
  refreshToken: number,
  interactionMode: NotebookInteractionMode,
  goal: string,
): ActivePlanningRequest {
  const maxOptions = interactionMode === "action" ? 1 : 3;
  const scopeKey = JSON.stringify({
    projectRoot,
    notebookId,
    interactionMode,
  });
  const requestKey = `${scopeKey}:${refreshToken}`;
  const current = planningRequests.get(scopeKey);
  if (current?.requestKey === requestKey) return current;
  const attemptId = `attempt_${
    globalThis.crypto?.randomUUID?.().replace(/-/g, "") ??
    `${Date.now()}_${Math.random().toString(16).slice(2)}`
  }`;
  const controller = new AbortController();
  const promise = proposeNotebookOptions(projectRoot, notebookId, maxOptions, {
    attemptId,
    signal: controller.signal,
  });
  const request = {
    scopeKey,
    requestKey,
    attemptId,
    controller,
    promise,
    projectRoot,
    notebookId,
    interactionMode,
    goal: boundedActivityText(goal),
    activityRecorded: false,
    startedAt: Date.now(),
  };
  planningRequests.set(scopeKey, request);
  const release = () => {
    if (planningRequests.get(scopeKey)?.promise === promise) {
      planningRequests.delete(scopeKey);
    }
  };
  void promise.then(release, release);
  void promise.then(
    (response) => {
      recordNotebookPlanningActivity(request, {
        status: "completed",
        option_count: response.options.length,
        trace_id: response.trace_id,
      });
    },
    (error: unknown) => {
      const failure = failurePacket(error);
      recordNotebookPlanningActivity(request, {
        status: controller.signal.aborted || failure.code === "NOTEBOOK_PLANNING_CANCELLED"
          ? "cancelled"
          : "error",
        error: failure.code,
      });
    },
  );
  return request;
}

function recordNotebookPlanningActivity(
  request: ActivePlanningRequest,
  outcome: Pick<NotebookPlanActivityRecord, "status" | "option_count" | "trace_id" | "error">,
) {
  if (request.activityRecorded) return;
  request.activityRecorded = true;
  appendAiActivity(request.projectRoot, {
    kind: "notebook_plan",
    id: makeActivityId(),
    at: new Date().toISOString(),
    notebook_id: request.notebookId,
    interaction_mode: request.interactionMode,
    goal: request.goal,
    ...outcome,
  });
}

function boundedActivityText(value: string, maximum = 500): string {
  const normalized = value.trim();
  return normalized.length <= maximum
    ? normalized
    : `${normalized.slice(0, Math.max(0, maximum - 1))}…`;
}

function failurePacket(error: unknown): { code: string; message: string } {
  const candidate = error as ApiErrorLike | null;
  const code = typeof candidate?.code === "string" && candidate.code.trim()
    ? candidate.code
    : "NOTEBOOK_LOAD_FAILED";
  return {
    code,
    message: error instanceof Error ? error.message : "Notebook request failed",
  };
}

function persistedInteractionMode(notebook: NotebookRecord): NotebookInteractionMode {
  return notebook.user_focus?.interaction_mode === "action" ? "action" : "plan";
}

function isMissingNotebook(error: unknown): boolean {
  const candidate = error as ApiErrorLike | null;
  return candidate?.code === "NOTEBOOK_NOT_FOUND" || candidate?.status === 404;
}

function recordValue(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return {};
  return value as Record<string, unknown>;
}

function requiredString(value: unknown, field: string): string {
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(`Notebook context field ${field} is missing`);
  }
  return value;
}

function requiredNumber(value: unknown, field: string): number {
  if (typeof value !== "number" || Number.isNaN(value)) {
    throw new Error(`Notebook context field ${field} is not a number`);
  }
  return value;
}

function optionalDomainMemoryProjection(value: unknown): DomainMemoryRetrievalProjection | null {
  if (value === null || value === undefined) return null;
  const item = recordValue(value);
  if (
    (item.contract_version !== "domain-memory-context-input/v1" &&
      item.contract_version !== "domain-memory-context-input/v2" &&
      item.contract_version !== "domain-memory-context-input/v3") ||
    item.memory_authority !== "non_authoritative" ||
    item.bounded !== true ||
    typeof item.retrieval_ref !== "string" ||
    typeof item.scope_ref !== "string" ||
    typeof item.preference_ref !== "string" ||
    !Array.isArray(item.entries) ||
    !Array.isArray(item.omissions)
  ) {
    throw new Error("Notebook context domain-memory projection is invalid");
  }
  return item as unknown as DomainMemoryRetrievalProjection;
}

function contextSlice(
  response: NotebookContextResponse,
  traceEvents: Array<Record<string, unknown>>,
): NotebookContextSlice {
  const omissions = response.omissions.map((raw, index) => {
    const item = recordValue(raw);
    const omittedByType = Array.isArray(item.omitted_by_type)
      ? item.omitted_by_type.map((entry) => {
          const typed = recordValue(entry);
          return {
            artifact_type: requiredString(typed.artifact_type, `omissions[${index}].artifact_type`),
            count: requiredNumber(typed.count, `omissions[${index}].count`),
          };
        })
      : [];
    return {
      section: requiredString(item.section, `omissions[${index}].section`),
      included_count: requiredNumber(
        item.included_count,
        `omissions[${index}].included_count`,
      ),
      available_count: requiredNumber(
        item.available_count,
        `omissions[${index}].available_count`,
      ),
      reason: requiredString(item.reason, `omissions[${index}].reason`),
      omitted_by_type: omittedByType,
    };
  });

  const budget = recordValue(response.budget_report);
  const sections = Array.isArray(budget.sections)
    ? budget.sections.map((entry, index) => {
        const item = recordValue(entry);
        return {
          section: requiredString(item.section, `budget_report.sections[${index}].section`),
          used_bytes: requiredNumber(
            item.used_bytes,
            `budget_report.sections[${index}].used_bytes`,
          ),
          budget_bytes: requiredNumber(
            item.budget_bytes,
            `budget_report.sections[${index}].budget_bytes`,
          ),
        };
      })
    : typeof budget.content_chars === "number" &&
        typeof budget.content_chars_budget === "number"
      ? [
          {
            section: "content_chars",
            used_bytes: budget.content_chars,
            budget_bytes: budget.content_chars_budget,
          },
        ]
      : [];
  const budgetUnit =
    sections.length > 0 && typeof budget.content_chars === "number"
      ? "characters" as const
      : "bytes" as const;
  const totalUsed =
    typeof budget.total_used_bytes === "number"
      ? budget.total_used_bytes
      : requiredNumber(budget.content_chars, "budget_report.content_chars");
  const totalBudget =
    typeof budget.total_budget_bytes === "number"
      ? budget.total_budget_bytes
      : requiredNumber(budget.content_chars_budget, "budget_report.content_chars_budget");

  const sourceManifest = response.source_manifest.map((raw, index) => {
    const item = recordValue(raw);
    const kind = typeof item.kind === "string" ? item.kind : "source";
    const id = typeof item.id === "string" ? item.id : String(index + 1);
    return {
      source_ref: `${kind}:${id}`,
      revision: typeof item.revision === "number" ? item.revision : 1,
      selection_reason:
        typeof item.selection_reason === "string"
          ? item.selection_reason
          : "included by bounded context compiler",
      never_truncated: item.never_truncated === true,
    };
  });

  const artifactCounts = Object.entries(response.artifact_type_counts).map(
    ([artifact_type, count]) => ({ artifact_type, count }),
  );

  const trace: TraceEvent[] = traceEvents.map((raw, index) => {
    const payload = recordValue(raw.payload);
    return {
      event_id:
        typeof raw.event_id === "string"
          ? raw.event_id
          : `${response.trace_id ?? response.context_id}:${index + 1}`,
      sequence: typeof raw.sequence === "number" ? raw.sequence : index + 1,
      event_type: requiredString(raw.event_type, `trace[${index}].event_type`),
      occurred_at:
        typeof raw.occurred_at === "string" ? raw.occurred_at : "unknown time",
      summary:
        Object.keys(payload).length > 0
          ? Object.entries(payload)
              .slice(0, 3)
              .map(([key, value]) => `${key}=${String(value)}`)
              .join(", ")
          : "recorded",
    };
  });

  return {
    context_id: requiredString(response.context_id, "context_id"),
    context_profile: requiredString(response.context_profile, "context_profile"),
    generation_context_hash: requiredString(
      response.generation_context_hash,
      "generation_context_hash",
    ),
    freshness_dependency_fingerprint: requiredString(
      response.freshness_dependency_fingerprint,
      "freshness_dependency_fingerprint",
    ),
    artifact_type_counts: artifactCounts,
    omissions,
    budget_report: {
      sections,
      total_used_bytes: totalUsed,
      total_budget_bytes: totalBudget,
      unit: budgetUnit,
    },
    source_manifest: sourceManifest,
    trace,
    domain_memory_projection: optionalDomainMemoryProjection(response.domain_memory_projection),
  };
}

function optionExecution(option: NotebookOptionRevision): OptionExecution {
  return parseOptionExecution({
    contract_version: "1.0",
    option_id: option.option_id,
    option_revision: option.option_revision,
    proposal_id: option.typed_proposal_id,
    proposal_revision: option.typed_proposal_revision,
    freshness_dependency_fingerprint: option.freshness_dependency_fingerprint,
    generation_context_id: option.generation_context_id,
    run_id: null,
  });
}

function narrative(notebook: NotebookRecord, options: NotebookOptionRevision[]) {
  const occurredAt = notebook.created_at ?? new Date(0).toISOString();
  return [
    {
      entry_id: `${notebook.notebook_id}:title`,
      kind: "user" as const,
      text: notebook.title,
      occurred_at: occurredAt,
    },
    ...(options.length > 0
      ? [
          {
            entry_id: `${notebook.notebook_id}:plan`,
            kind: "agent" as const,
            text: `Proposed ${options.length} typed analysis option${options.length === 1 ? "" : "s"}.`,
            occurred_at: occurredAt,
          },
        ]
      : []),
  ];
}

function readyView(
  notebook: NotebookRecord,
  context: NotebookContextSlice,
  options: NotebookOptionRevision[],
  extras: Partial<NotebookData> = {},
): NotebookReadyView {
  return {
    status: "ready",
    notebook: {
      notebook_id: notebook.notebook_id,
      run_family_id: notebook.run_family_id,
      narrative: narrative(notebook, options),
      options,
      contextSlice: context,
      confirmation: null,
      execution: null,
      result: null,
      outcome: null,
      selection: null,
      ...extras,
    },
  };
}

function replaceOption(
  view: NotebookReadyView,
  option: NotebookOptionRevision,
  extras: Partial<NotebookData> = {},
): NotebookReadyView {
  const options = view.notebook.options.map((item) =>
    item.option_id === option.option_id ? option : item,
  );
  return readyView(
    {
      notebook_id: view.notebook.notebook_id,
      run_family_id: view.notebook.run_family_id,
      title: view.notebook.narrative[0]?.text ?? "Notebook",
      created_by: "user",
      active_head_run_id: null,
    },
    view.notebook.contextSlice!,
    options,
    {
      ...view.notebook,
      ...extras,
      options,
    },
  );
}

export interface NotebookRouteViewProps {
  projectRoot: string;
  activeRunId?: string | null;
  onMaterializedDraft?: (response: NotebookMaterializationResponse) => void;
  onOpenMemorySettings?: () => void;
}

export function NotebookRouteView({
  projectRoot,
  activeRunId = null,
  onMaterializedDraft,
  onOpenMemorySettings,
}: NotebookRouteViewProps) {
  const agent = useAgentSurfaceOptional();
  const workbench = useWorkbenchOptional();
  const forest = useForest();
  const draftActions = useDraftActions();
  const [searchParams, setSearchParams] = useSearchParams();
  const [notebookId, setNotebookId] = useState<string | null>(
    searchParams.get("notebook"),
  );
  const [routeChoices, setRouteChoices] = useState<NotebookRecord[] | null>(null);
  const [view, setView] = useState<NotebookView>({ status: "loading" });
  const [busy, setBusy] = useState(false);
  const [planning, setPlanning] = useState(false);
  // Server-published total planning budget, kept so the planning surface can
  // show what it is running against instead of an open-ended counter.
  const [planningDeadline, setPlanningDeadline] = useState<number | undefined>(undefined);
  // Epoch ms of the in-flight planning attempt, recovered from the module-level
  // request registry so a remount keeps counting the same attempt.
  const [planningStartedAt, setPlanningStartedAt] = useState<number | undefined>(undefined);
  const [planningError, setPlanningError] = useState<{
    code: string;
    message: string;
  } | null>(null);
  const [actionError, setActionError] = useState<{
    code: string;
    message: string;
  } | null>(null);
  const [refreshToken, setRefreshToken] = useState(0);
  const [reloadToken, setReloadToken] = useState(0);
  const [uploadBusy, setUploadBusy] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [notebookIntent, setNotebookIntent] = useState("");
  const [notebookInteractionMode, setNotebookInteractionMode] =
    useState<NotebookInteractionMode>("plan");
  const [domainMemoryCandidates, setDomainMemoryCandidates] = useState<DomainMemoryCandidate[] | undefined>(undefined);
  const [domainMemoryCandidateError, setDomainMemoryCandidateError] = useState<string | null>(null);
  const [domainMemoryReviewBusy, setDomainMemoryReviewBusy] = useState(false);
  const domainMemoryProjectRootRef = useRef(projectRoot);
  domainMemoryProjectRootRef.current = projectRoot;
  const initializationClaimedRef = useRef(false);
  const lastLoadKeyRef = useRef<string | null>(null);
  const lastReadyViewRef = useRef<NotebookReadyView | null>(null);
  const activePlanningRef = useRef<ActivePlanningRequest | null>(null);
  const completedPlanningTokenRef = useRef(0);
  const loadGenerationRef = useRef(0);
  const domainMemoryGenerationRef = useRef(0);

  const loadDomainMemoryCandidates = useCallback(async () => {
    const generation = domainMemoryGenerationRef.current + 1;
    domainMemoryGenerationRef.current = generation;
    setDomainMemoryCandidates(undefined);
    setDomainMemoryCandidateError(null);
    if (!notebookId) return;
    try {
      const response = await listDomainMemoryCandidates(projectRoot);
      if (generation !== domainMemoryGenerationRef.current) return;
      setDomainMemoryCandidates(response.candidates);
    } catch (error: unknown) {
      if (generation !== domainMemoryGenerationRef.current) return;
      const failure = failurePacket(error);
      setDomainMemoryCandidateError(`${failure.code}: ${failure.message}`);
    }
  }, [notebookId, projectRoot]);

  useEffect(() => {
    setDomainMemoryReviewBusy(false);
    void loadDomainMemoryCandidates();
    return () => {
      domainMemoryGenerationRef.current += 1;
    };
  }, [loadDomainMemoryCandidates]);

  const reviewNotebookMemoryCandidate = useCallback(async (
    candidateId: string,
    decision: "approved" | "rejected",
    revision: number,
  ) => {
    if (domainMemoryReviewBusy) return;
    const requestedProjectRoot = projectRoot;
    const generation = domainMemoryGenerationRef.current;
    setDomainMemoryReviewBusy(true);
    setDomainMemoryCandidateError(null);
    try {
      const now = new Date();
      await reviewDomainMemoryCandidate(projectRoot, candidateId, decision === "approved"
        ? {
            decision,
            expected_revision: revision,
            actor_id: "local-user",
            approved_at: now.toISOString(),
            review_after: new Date(now.getTime() + 90 * 24 * 60 * 60 * 1000).toISOString(),
          }
        : {
            decision,
            expected_revision: revision,
            actor_id: "local-user",
          });
      if (
        generation !== domainMemoryGenerationRef.current ||
        domainMemoryProjectRootRef.current !== requestedProjectRoot
      ) return;
      await loadDomainMemoryCandidates();
    } catch (error: unknown) {
      if (
        generation !== domainMemoryGenerationRef.current ||
        domainMemoryProjectRootRef.current !== requestedProjectRoot
      ) return;
      const failure = failurePacket(error);
      setDomainMemoryCandidateError(`${failure.code}: ${failure.message}`);
    } finally {
      if (domainMemoryProjectRootRef.current === requestedProjectRoot) {
        setDomainMemoryReviewBusy(false);
      }
    }
  }, [domainMemoryReviewBusy, loadDomainMemoryCandidates, projectRoot]);

  const load = useCallback(async () => {
    const generation = loadGenerationRef.current + 1;
    loadGenerationRef.current = generation;
    const preserved = lastReadyViewRef.current;
    const explicitReplan = refreshToken > completedPlanningTokenRef.current;
    if (!(explicitReplan && preserved)) {
      setView({ status: "loading" });
    }
    let discoveredNotebooks: NotebookRecord[] | null = null;
    try {
      let notebook: NotebookRecord;
      if (notebookId) {
        try {
          notebook = await getNotebook(projectRoot, notebookId);
        } catch (error) {
          // A Notebook is a durable project projection. A deep link can outlive
          // a deleted projection, but recovering is only safe when this project
          // has exactly one remaining Notebook; otherwise retain the error rather
          // than silently choosing a different analysis.
          if (!isMissingNotebook(error)) throw error;
          const persisted = await listNotebooks(projectRoot);
          discoveredNotebooks = persisted;
          if (persisted.length !== 1) throw error;
          notebook = persisted[0];
          setNotebookId(notebook.notebook_id);
          const next = new URLSearchParams(searchParams);
          next.set("notebook", notebook.notebook_id);
          setSearchParams(next, { replace: true });
        }
      } else {
        const persisted = await listNotebooks(projectRoot);
        discoveredNotebooks = persisted;
        if (persisted.length === 1) {
          // The Notebook is a durable project projection, not a view-local
          // cache.  Outer Workbench navigation can intentionally drop the
          // `notebook` query parameter; recover the sole persisted projection
          // before attempting to derive one from the currently focused Run.
          notebook = persisted[0];
        } else if (activeRunId) {
          notebook = await ensureNotebookProjection(projectRoot, {
            from_run_id: activeRunId,
            created_by: "user",
            title: "Analysis Notebook",
          });
        } else {
          setRouteChoices(persisted.length > 0 ? persisted : null);
          return;
        }
        setNotebookId(notebook.notebook_id);
        const next = new URLSearchParams(searchParams);
        next.set("notebook", notebook.notebook_id);
        setSearchParams(next, { replace: true });
      }
      setRouteChoices(null);
      const userGoal = typeof notebook.user_focus?.goal === "string"
        ? notebook.user_focus.goal.trim()
        : "";
      setNotebookIntent(userGoal);
      const interactionMode = persistedInteractionMode(notebook);
      setNotebookInteractionMode(interactionMode);

      const compiled = await compileNotebookContext(projectRoot, notebook.notebook_id);
      let snapshot: NotebookPlanningResponse;
      if (explicitReplan && userGoal) {
        const request = proposeNotebookOptionsOnce(
            projectRoot,
            notebook.notebook_id,
            refreshToken,
            interactionMode,
            userGoal,
          );
        activePlanningRef.current = request;
        setPlanningError(null);
        setPlanningStartedAt(request.startedAt);
        setPlanning(true);
        if (!preserved) setView({ status: "loading", phase: "planning" });
        snapshot = await request.promise;
        completedPlanningTokenRef.current = refreshToken;
      } else {
        snapshot = await listNotebookOptions(projectRoot, notebook.notebook_id);
      }
      if (snapshot.options.length === 0 && userGoal) {
        const request = proposeNotebookOptionsOnce(
          projectRoot,
          notebook.notebook_id,
          refreshToken,
          interactionMode,
          userGoal,
        );
        activePlanningRef.current = request;
        setPlanningError(null);
        setPlanningStartedAt(request.startedAt);
        setPlanning(true);
        if (!preserved) setView({ status: "loading", phase: "planning" });
        snapshot = await request.promise;
        completedPlanningTokenRef.current = refreshToken;
      }
      const traceId = snapshot.trace_id ?? compiled.trace_id;
      const trace = traceId
        ? await getNotebookTrace(projectRoot, notebook.notebook_id, traceId)
        : { trace_id: "", events: [] };
      const options = snapshot.options.map(parseNotebookOptionRevision);
      const executionResults = Object.fromEntries(
        Object.entries(snapshot.execution_results ?? {}).map(([optionId, raw]) => [
          optionId,
          parseNotebookExecutionResult(raw),
        ]),
      );
      const publishedDeadline = snapshot.context?.planning_deadline_s;
      if (typeof publishedDeadline === "number") setPlanningDeadline(publishedDeadline);
      const context = contextSlice(snapshot.context ?? compiled, trace.events);
      // A Notebook can retain multiple materialized siblings. The handoff
      // shown above the narrative must belong to the newest materialized
      // revision, not whichever option happens to sort first by option_id.
      // Otherwise a reload can display an old Draft while the user is working
      // on a newer Option.
      const persistedMaterialization = options
        .filter((option) => option.lifecycle_status === "materialized" || option.lifecycle_status === "executed")
        .sort((a, b) => b.created_at.localeCompare(a.created_at))
        .map((option) => snapshot.materializations?.[option.option_id])
        .find((value): value is Record<string, unknown> => value !== undefined);
      const materialization = persistedMaterialization
        ? parseOptionMaterialization(persistedMaterialization)
        : null;
      if (generation !== loadGenerationRef.current) return;
      const nextView = readyView(notebook, context, options, {
        materialization,
        executionResults,
      });
      lastReadyViewRef.current = nextView;
      setView(nextView);
    } catch (error: unknown) {
      if (generation !== loadGenerationRef.current) return;
      if (discoveredNotebooks?.length) {
        setRouteChoices(discoveredNotebooks);
        return;
      }
      if (!notebookId) initializationClaimedRef.current = false;
      const failure = failurePacket(error);
      if (lastReadyViewRef.current && activePlanningRef.current) {
        setPlanningError(failure);
        setView(lastReadyViewRef.current);
      } else {
        setView({ status: "error", error: failure });
      }
    } finally {
      if (generation === loadGenerationRef.current) {
        activePlanningRef.current = null;
        setPlanning(false);
        setPlanningStartedAt(undefined);
      }
    }
  }, [
    activeRunId,
    notebookId,
    projectRoot,
    reloadToken,
    refreshToken,
    searchParams,
    setSearchParams,
  ]);

  useEffect(() => {
    const loadKey = JSON.stringify({
      projectRoot,
      notebookId,
      activeRunId,
      refreshToken,
      reloadToken,
    });
    if (lastLoadKeyRef.current === loadKey) return;
    lastLoadKeyRef.current = loadKey;
    // React StrictMode may invoke this effect twice before the first async
    // request yields. Claim a runless initialization before calling load so a
    // second invocation cannot create a second notebook/run-family pair.
    if (refreshToken === 0 && initializationClaimedRef.current) {
      return;
    }
    if (refreshToken === 0 && !notebookId && activeRunId) initializationClaimedRef.current = true;
    void load();
  }, [
    activeRunId,
    load,
    notebookId,
    projectRoot,
    reloadToken,
    refreshToken,
  ]);

  async function startWithDataset(file: File) {
    setUploadBusy(true);
    setUploadError(null);
    try {
      const upload = await uploadDataset(projectRoot, file);
      const notebook = await ensureNotebookProjection(projectRoot, {
        dataset: {
          upload_sha256: upload.sha256,
          filename: upload.filename,
          sheet_names: [],
        },
        created_by: "user",
        title: "Analysis Notebook",
      });
      setRouteChoices(null);
      setNotebookId(notebook.notebook_id);
      const next = new URLSearchParams(searchParams);
      next.set("notebook", notebook.notebook_id);
      setSearchParams(next, { replace: true });
      setView({ status: "loading" });
    } catch (error: unknown) {
      setUploadError(error instanceof Error ? error.message : "Dataset upload failed");
    } finally {
      setUploadBusy(false);
    }
  }

  async function startFromSourceRun() {
    if (!activeRunId) return;
    setUploadBusy(true);
    setUploadError(null);
    try {
      const notebook = await ensureNotebookDatasetProjection(projectRoot, {
        from_run_id: activeRunId,
        created_by: "user",
        title: "New analysis from source data",
      });
      initializationClaimedRef.current = false;
      setRouteChoices(null);
      setNotebookId(notebook.notebook_id);
      const next = new URLSearchParams(searchParams);
      next.set("notebook", notebook.notebook_id);
      setSearchParams(next, { replace: true });
      setView({ status: "loading" });
    } catch (error: unknown) {
      setUploadError(
        error instanceof Error ? error.message : "Could not start from source data",
      );
    } finally {
      setUploadBusy(false);
    }
  }

  function updateWithOption(option: NotebookOptionRevision, extras: Partial<NotebookData> = {}) {
    setView((current) => {
      if (current.status !== "ready") return current;
      const next = replaceOption(current, option, extras);
      lastReadyViewRef.current = next;
      return next;
    });
  }

  async function decide(option: NotebookOptionRevision, decision: "deferred" | "rejected") {
    try {
      const response = await recordNotebookDecision(projectRoot, option.notebook_id, option.option_id, {
        decision,
        actor: "user",
      });
      const next = parseNotebookOptionRevision(response);
      updateWithOption(next, { confirmation: null });
    } catch (error: unknown) {
      setView({ status: "error", error: failurePacket(error) });
    }
  }

  function cancelPlanning() {
    const active = activePlanningRef.current;
    if (!active || !notebookId) return;
    loadGenerationRef.current += 1;
    activePlanningRef.current = null;
    if (planningRequests.get(active.scopeKey)?.requestKey === active.requestKey) {
      planningRequests.delete(active.scopeKey);
    }
    active.controller.abort();
    recordNotebookPlanningActivity(active, {
      status: "cancelled",
      error: "NOTEBOOK_PLANNING_CANCELLED",
    });
    setPlanning(false);
    setPlanningStartedAt(undefined);
    setPlanningError(null);
    if (lastReadyViewRef.current) {
      setView(lastReadyViewRef.current);
    } else {
      setView({
        status: "error",
        error: {
          code: "NOTEBOOK_PLANNING_CANCELLED",
          message: "Notebook planning was cancelled",
        },
      });
    }
    void cancelNotebookPlanning(projectRoot, notebookId, active.attemptId).catch(
      (error: unknown) => {
        const failure = failurePacket(error);
        setPlanningError({
          code: "NOTEBOOK_PLANNING_CANCEL_FAILED",
          message:
            `Workbench stopped waiting, but backend cancellation was not confirmed: ` +
            `${failure.code} — ${failure.message}`,
        });
      },
    );
  }

  function revalidateOption() {
    setRefreshToken((token) => token + 1);
  }

  async function submitNotebookIntent(goal: string) {
    if (!notebookId) return;
    setActionError(null);
    try {
      const notebook = await updateNotebookFocus(projectRoot, notebookId, {
        goal,
        interaction_mode: notebookInteractionMode,
      });
      setNotebookIntent(typeof notebook.user_focus?.goal === "string" ? notebook.user_focus.goal : goal);
      setNotebookInteractionMode(persistedInteractionMode(notebook));
      setRefreshToken((token) => token + 1);
    } catch (error: unknown) {
      setActionError(failurePacket(error));
    }
  }

  async function changeNotebookInteractionMode(mode: NotebookInteractionMode) {
    if (!notebookId || mode === notebookInteractionMode) return;
    setActionError(null);
    try {
      const notebook = await updateNotebookFocus(projectRoot, notebookId, {
        interaction_mode: mode,
      });
      setNotebookIntent(
        typeof notebook.user_focus?.goal === "string"
          ? notebook.user_focus.goal
          : notebookIntent,
      );
      setNotebookInteractionMode(persistedInteractionMode(notebook));
      // Mode changes preserve prior history but do not begin planning or execution.
      setReloadToken((token) => token + 1);
    } catch (error: unknown) {
      setActionError(failurePacket(error));
    }
  }

  function showConfirmation(
    option: NotebookOptionRevision,
    mode: "materialize" | "confirm_and_execute" = "materialize",
  ) {
    setActionError(null);
    const execution = optionExecution(option);
    const planDiff: PlanDiffLine[] = [
      {
        field: "typed_proposal",
        from: null,
        to: `${option.typed_proposal_id} rev ${option.typed_proposal_revision}`,
      },
    ];
    setView((current) => {
      if (current.status !== "ready") return current;
      return {
        ...current,
        notebook: {
          ...current.notebook,
          confirmation: { option, execution, plan_diff: planDiff, mode },
        },
      };
    });
  }

  async function selectOption(option: NotebookOptionRevision) {
    try {
      if (option.lifecycle_status === "selected") {
        showConfirmation(option);
        return;
      }
      const response = await recordNotebookDecision(
        projectRoot,
        option.notebook_id,
        option.option_id,
        {
        decision: "selected",
        actor: "user",
        },
      );
      const selected = parseNotebookOptionRevision(response);
      updateWithOption(selected);
      showConfirmation(selected);
    } catch (error: unknown) {
      setView({ status: "error", error: failurePacket(error) });
    }
  }

  async function confirm(selection: PendingConfirmation) {
    setBusy(true);
    setActionError(null);
    try {
      if (selection.mode === "confirm_and_execute") {
        await confirmAndExecuteNotebookOption(
          projectRoot,
          selection.option.notebook_id,
          selection.option.option_id,
          {
            option_revision: selection.option.option_revision,
            proposal_id: selection.option.typed_proposal_id,
            proposal_revision: selection.option.typed_proposal_revision,
          },
        );
        // A completed workflow can publish several sibling runs. Refresh the
        // forest before reloading the Notebook so the Global Agent receives a
        // new, durable project overview instead of continuing on the source
        // run that existed when its session was created.
        forest?.refetch?.();
        setView((current) =>
          current.status === "ready"
            ? { ...current, notebook: { ...current.notebook, confirmation: null } }
            : current,
        );
        setReloadToken((token) => token + 1);
        return;
      }
      const response = await confirmNotebookOption(
        projectRoot,
        selection.option.notebook_id,
        selection.option.option_id,
        {
          option_revision: selection.option.option_revision,
          proposal_id: selection.option.typed_proposal_id,
          proposal_revision: selection.option.typed_proposal_revision,
        },
      );
      const packet = recordValue(response);
      if ("workflow_execution" in packet) {
        // See the equivalent confirm-and-execute path above.  The normal
        // confirmation endpoint may execute a composed workflow synchronously
        // and therefore needs the same project-context refresh.
        forest?.refetch?.();
        setView((current) =>
          current.status === "ready"
            ? { ...current, notebook: { ...current.notebook, confirmation: null } }
            : current,
        );
        setReloadToken((token) => token + 1);
        return;
      }
      if (!("materialization" in packet)) {
        setView((current) =>
          current.status === "ready"
            ? { ...current, notebook: { ...current.notebook, confirmation: null } }
            : current,
        );
        setReloadToken((token) => token + 1);
        return;
      }
      const materializationResponse = response as unknown as NotebookMaterializationResponse;
      const materialization = parseOptionMaterialization(materializationResponse.materialization);
      draftActions?.onForkDraft(materializationResponse);
      onMaterializedDraft?.(materializationResponse);
      forest?.refetch?.();
      const materialized = { ...selection.option, lifecycle_status: "materialized" as const };
      updateWithOption(materialized, { confirmation: null, materialization });
      const nodeKey =
        materialization.draft_execution_mode === "genesis"
          ? `draft:${materialization.draft_id}:model_1`
          : `draft:${materialization.draft_id}`;
      const next = new URLSearchParams(searchParams);
      next.set("view", "graph");
      next.set("notebook", selection.option.notebook_id);
      next.set("panel", "agent");
      next.set("tabs", nodeKey);
      next.set("active", nodeKey);
      next.set("focus", nodeKey);
      setSearchParams(next);
    } catch (error: unknown) {
      setActionError(failurePacket(error));
    } finally {
      setBusy(false);
    }
  }

  function confirmAndExecute(option: NotebookOptionRevision) {
    showConfirmation(option, "confirm_and_execute");
  }

  async function cancel(selection: PendingConfirmation) {
    void selection;
    setActionError(null);
    setView((current) =>
      current.status === "ready"
        ? { ...current, notebook: { ...current.notebook, confirmation: null } }
        : current,
    );
  }

  const [selectionDraft, setSelectionDraft] = useState("");
  const [selectionAction, setSelectionAction] = useState<string | null>(null);
  const [selectionNotice, setSelectionNotice] = useState<string | null>(null);
  const [selectionAnchor, setSelectionAnchor] = useState<NotebookSelectionAnchor | null>(null);

  function handleTextSelection(
    selection: NotebookSelection,
    anchor: NotebookSelectionAnchor,
  ) {
    setSelectionAnchor(anchor);
    setView((current) =>
      current.status === "ready"
        ? {
            ...current,
            notebook: {
              ...current.notebook,
              selection,
            },
          }
        : current,
    );
  }

  function onSelectionAction(
    selection: NotebookSelection,
    action: "ask" | "explain" | "follow_up" | "note" | "defer",
  ) {
    const prefixes = {
      ask: "Use this selected passage in my next analysis question:",
      explain: "Explain the selected passage and cite the source:",
      follow_up: "Answer this targeted follow-up about the selected passage:",
      note: "Prepare a note from this selected passage:",
      defer: "Prepare a deferred analysis option from this selected passage:",
    } as const;
    const draft = `${prefixes[action]}\n\n"${selection.text}"\nSource: ${selection.source_ref}\n\n`;
    setSelectionAction(action);
    setSelectionDraft(draft);
    setSelectionNotice(null);
    agent?.setPrompt(draft);
    dismissSelectionSurface();
  }

  function dismissSelectionSurface() {
    setSelectionAnchor(null);
    setView((current) =>
      current.status === "ready"
        ? { ...current, notebook: { ...current.notebook, selection: null } }
        : current,
    );
  }

  function useSelectionDraft() {
    agent?.setPrompt(selectionDraft);
    setSelectionNotice(
      agent
        ? "Added to the Agent prompt. Edit or send it from the Agent composer."
        : "Question prepared. The current view has no Agent composer mounted.",
    );
  }

  function askInSideChat(selection: NotebookSelection) {
    onSelectionAction(selection, "follow_up");
    if (agent && workbench) {
      workbench.dispatch.setBottomPanel("agent");
      setSelectionNotice("Added to the Agent side chat. Edit or send it there.");
    } else {
      setSelectionNotice("Prepared the question, but this runless view has no side chat mounted.");
    }
  }

  function openRouteNotebook(notebook: NotebookRecord) {
    initializationClaimedRef.current = false;
    setRouteChoices(null);
    setNotebookId(notebook.notebook_id);
    const next = new URLSearchParams(searchParams);
    next.set("notebook", notebook.notebook_id);
    setSearchParams(next, { replace: true });
    setView({ status: "loading" });
  }

  if (routeChoices?.length) {
    return (
      <section className="nb-dataset-start" data-testid="notebook-route-chooser">
        <span className="nb-label">Choose an existing analysis</span>
        <h2>Several durable Notebooks are available</h2>
        <p>
          Workbench cannot safely infer which analysis you meant. Choose one to open it,
          or start a new analysis from verified source data.
        </p>
        <div className="nb-route-choice-list">
          {routeChoices.map((notebook) => (
            <button
              key={notebook.notebook_id}
              type="button"
              data-testid={`notebook-choice-${notebook.notebook_id}`}
              onClick={() => openRouteNotebook(notebook)}
    >
              <strong>{notebook.title || "Untitled analysis"}</strong>
              <span>{notebook.active_head_run_id ?? "No completed Run"}</span>
            </button>
          ))}
        </div>
      </section>
    );
  }

  if (!notebookId && !activeRunId) {
    return (
      <section className="nb-dataset-start" data-testid="notebook-dataset-start">
        <span className="nb-label">Start with a verified dataset</span>
        <h2>Bring the raw data into a bounded Notebook context</h2>
        <p>
          This uses the same project data store as Import data and create analysis.
          The Agent first inspects a bounded profile and evidence pack, but this path
          does not create a Run until you review, confirm, and execute an option.
        </p>
        <label htmlFor="notebook-dataset-upload">Dataset</label>
        <input
          id="notebook-dataset-upload"
          aria-label="Dataset"
          type="file"
          accept=".csv,.xlsx,.xls,.tsv"
          disabled={uploadBusy}
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) void startWithDataset(file);
          }}
        />
        {uploadBusy ? <p data-testid="notebook-dataset-uploading">Uploading and verifying…</p> : null}
        {uploadError ? <p role="alert" data-testid="notebook-dataset-error">{uploadError}</p> : null}
      </section>
    );
  }

  return (
    <div
      data-testid="notebook-route-view"
      style={{ flex: 1, minHeight: 0, overflow: "auto", padding: 20 }}
      onPointerDown={(event) => {
        const target = event.target as HTMLElement | null;
        if (
          !target?.closest('[data-testid="notebook-selection-actions"]') &&
          !target?.closest('[data-testid="notebook-surface"]')
        ) {
          dismissSelectionSurface();
        }
      }}
      >
      {uploadError ? <p role="alert" data-testid="notebook-source-restart-error">{uploadError}</p> : null}
      {domainMemoryCandidateError ? (
        <p
          role="status"
          data-testid="domain-memory-candidate-error"
          aria-live="polite"
        >
          {domainMemoryCandidateError}
        </p>
      ) : null}
      <section aria-label="Notebook memory" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, marginBottom: 16 }}>
        <span>Memory is managed per project in Settings and never applies automatically.</span>
        <button
          type="button"
          data-testid="notebook-manage-memory"
          className="nb-button"
          onClick={() => {
            if (onOpenMemorySettings) {
              onOpenMemorySettings();
              return;
            }
            const next = new URLSearchParams(searchParams);
            next.set("memory_settings", "1");
            setSearchParams(next);
          }}
        >
          Manage memory
        </button>
      </section>
      <NotebookSurface
        view={view}
        projectRoot={projectRoot}
        busy={busy}
        onStartNewAnalysis={activeRunId ? () => void startFromSourceRun() : undefined}
        newAnalysisDisabled={uploadBusy}
        onReplan={() => {
          if (notebookIntent.trim()) setRefreshToken((token) => token + 1);
          else setActionError({ code: "NOTEBOOK_GOAL_REQUIRED", message: "Describe what you want to find out before planning options." });
        }}
        interactionMode={notebookInteractionMode}
        onInteractionModeChange={(mode) => void changeNotebookInteractionMode(mode)}
        userIntent={notebookIntent}
        onUserIntent={(goal) => void submitNotebookIntent(goal)}
        onCancelPlanning={cancelPlanning}
        planningDeadlineSeconds={planningDeadline}
        planningStartedAtMs={planningStartedAt}
        planning={planning}
        planningError={planningError}
        actionError={actionError}
        onTextSelection={handleTextSelection}
        onDismissSelection={dismissSelectionSurface}
        selectionAnchor={selectionAnchor}
        onSelectOption={selectOption}
        onDeferOption={(option) => void decide(option, "deferred")}
        onRejectOption={(option) => void decide(option, "rejected")}
        onRevalidateOption={revalidateOption}
        onConfirm={(selection) => void confirm(selection)}
        onCancelConfirmation={(selection) => void cancel(selection)}
        onConfirmAndExecute={confirmAndExecute}
        onSelectionAsk={(selection) => onSelectionAction(selection, "ask")}
        onSelectionExplain={(selection) => onSelectionAction(selection, "explain")}
        onSelectionFollowUp={askInSideChat}
        onSelectionSaveNote={(selection) => onSelectionAction(selection, "note")}
        onSelectionDefer={(selection) => onSelectionAction(selection, "defer")}
        domainMemoryCandidates={domainMemoryCandidates}
        onDomainMemoryCandidateReview={reviewNotebookMemoryCandidate}
      />
      {domainMemoryReviewBusy ? (
        <p data-testid="domain-memory-review-status" aria-live="polite">
          Saving memory review…
        </p>
      ) : null}
      {selectionDraft ? (
        <section className="nb-selection-composer" data-testid="notebook-selection-composer">
          <header className="nb-selection-composer-header">
            <span className="nb-label">Selected text follow-up</span>
            <span>{selectionAction ?? "question"}</span>
          </header>
          <label htmlFor="notebook-selection-question">Selected text question</label>
          <textarea
            id="notebook-selection-question"
            value={selectionDraft}
            onChange={(event) => {
              setSelectionDraft(event.target.value);
              setSelectionNotice(null);
            }}
            rows={5}
          />
          <div className="nb-selection-composer-actions">
            <button
              type="button"
              className="nb-button nb-button-primary"
              data-testid="selection-composer-use"
              onClick={useSelectionDraft}
            >
              Use in next Agent question
            </button>
          </div>
          {selectionNotice ? (
            <p className="nb-selection-composer-notice" data-testid="selection-composer-notice">
              {selectionNotice}
            </p>
          ) : null}
        </section>
      ) : null}
      {view.status === "ready" && view.notebook.options.length === 0 ? (
        <button
          type="button"
          className="nb-button nb-button-primary"
          data-testid="notebook-propose-options"
          onClick={() => setRefreshToken((token) => token + 1)}
        >
          Generate analysis options
        </button>
      ) : null}
    </div>
  );
}
