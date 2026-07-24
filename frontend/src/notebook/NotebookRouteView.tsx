import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { uploadDataset } from "../api";

import {
  compileNotebookContext,
  ensureNotebookProjection,
  getNotebook,
  getNotebookTrace,
  listNotebooks,
  listNotebookOptions,
  materializeNotebookOption,
  proposeNotebookOptions,
  recordNotebookDecision,
  type NotebookMaterializationResponse,
  type NotebookContextResponse,
  type NotebookRecord,
} from "./notebookApi";
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

type ApiErrorLike = Error & { code?: string | null };

function failurePacket(error: unknown): { code: string; message: string } {
  const candidate = error as ApiErrorLike | null;
  return {
    code: candidate?.code ?? "NOTEBOOK_LOAD_FAILED",
    message: error instanceof Error ? error.message : "Notebook request failed",
  };
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
}

export function NotebookRouteView({
  projectRoot,
  activeRunId = null,
  onMaterializedDraft,
}: NotebookRouteViewProps) {
  const agent = useAgentSurfaceOptional();
  const workbench = useWorkbenchOptional();
  const forest = useForest();
  const draftActions = useDraftActions();
  const [searchParams, setSearchParams] = useSearchParams();
  const [notebookId, setNotebookId] = useState<string | null>(
    searchParams.get("notebook"),
  );
  const [view, setView] = useState<NotebookView>({ status: "loading" });
  const [busy, setBusy] = useState(false);
  const [refreshToken, setRefreshToken] = useState(0);
  const [uploadBusy, setUploadBusy] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const initializationClaimedRef = useRef(false);

  const load = useCallback(async () => {
    setView({ status: "loading" });
    try {
      let notebook: NotebookRecord;
      if (notebookId) {
        notebook = await getNotebook(projectRoot, notebookId);
      } else {
        const persisted = await listNotebooks(projectRoot);
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
          return;
        }
        setNotebookId(notebook.notebook_id);
        const next = new URLSearchParams(searchParams);
        next.set("notebook", notebook.notebook_id);
        setSearchParams(next, { replace: true });
      }

      const compiled = await compileNotebookContext(projectRoot, notebook.notebook_id);
      let snapshot = refreshToken > 0
        ? await proposeNotebookOptions(projectRoot, notebook.notebook_id, 3)
        : await listNotebookOptions(projectRoot, notebook.notebook_id);
      if (snapshot.options.length === 0) {
        snapshot = await proposeNotebookOptions(projectRoot, notebook.notebook_id, 3);
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
      setView(readyView(notebook, context, options, { materialization, executionResults }));
    } catch (error: unknown) {
      if (!notebookId) initializationClaimedRef.current = false;
      setView({ status: "error", error: failurePacket(error) });
    }
  }, [activeRunId, notebookId, projectRoot, refreshToken, searchParams, setSearchParams]);

  useEffect(() => {
    // React StrictMode may invoke this effect twice before the first async
    // request yields. Claim a runless initialization before calling load so a
    // second invocation cannot create a second notebook/run-family pair.
    if (refreshToken === 0 && initializationClaimedRef.current) {
      return;
    }
    if (refreshToken === 0 && !notebookId && activeRunId) initializationClaimedRef.current = true;
    void load();
  }, [activeRunId, load, notebookId, refreshToken]);

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

  function updateWithOption(option: NotebookOptionRevision, extras: Partial<NotebookData> = {}) {
    setView((current) =>
      current.status === "ready" ? replaceOption(current, option, extras) : current,
    );
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

  function showConfirmation(option: NotebookOptionRevision) {
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
          confirmation: { option, execution, plan_diff: planDiff },
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
    try {
      const response = await materializeNotebookOption(
        projectRoot,
        selection.option.notebook_id,
        selection.option.option_id,
      );
      if (!response.materialization) {
        throw new Error("Notebook materialization response is missing its record");
      }
      const materialization = parseOptionMaterialization(response.materialization);
      draftActions?.onForkDraft(response);
      onMaterializedDraft?.(response);
      forest?.refetch?.();
      const materialized = { ...selection.option, lifecycle_status: "materialized" as const };
      updateWithOption(materialized, { confirmation: null, materialization });
    } catch (error: unknown) {
      setView({ status: "error", error: failurePacket(error) });
    } finally {
      setBusy(false);
    }
  }

  async function cancel(selection: PendingConfirmation) {
    void selection;
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

  if (!notebookId && !activeRunId) {
    return (
      <section className="nb-dataset-start" data-testid="notebook-dataset-start">
        <span className="nb-label">Start with a verified dataset</span>
        <h2>Bring the raw data into a bounded Notebook context</h2>
        <p>
          The Agent will inspect a bounded profile and evidence pack before it
          proposes any analysis. No Run or runless Notebook is created here.
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
      <NotebookSurface
        view={view}
        projectRoot={projectRoot}
        busy={busy}
        onReplan={() => setRefreshToken((token) => token + 1)}
        onTextSelection={handleTextSelection}
        onDismissSelection={dismissSelectionSurface}
        selectionAnchor={selectionAnchor}
        onSelectOption={selectOption}
        onDeferOption={(option) => void decide(option, "deferred")}
        onRejectOption={(option) => void decide(option, "rejected")}
        onConfirm={(selection) => void confirm(selection)}
        onCancelConfirmation={(selection) => void cancel(selection)}
        onSelectionAsk={(selection) => onSelectionAction(selection, "ask")}
        onSelectionExplain={(selection) => onSelectionAction(selection, "explain")}
        onSelectionFollowUp={askInSideChat}
        onSelectionSaveNote={(selection) => onSelectionAction(selection, "note")}
        onSelectionDefer={(selection) => onSelectionAction(selection, "defer")}
      />
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
