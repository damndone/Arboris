import { Fragment, useEffect, useRef, useState } from "react";

import "./notebook.css";
import { ContextSlicePanel } from "./ContextSlicePanel";
import { DomainMemoryControls } from "./DomainMemoryControls";
import { DomainMemoryEntryList } from "./DomainMemoryEntryList";
import { DomainMemoryReviewQueue } from "./DomainMemoryReviewQueue";
import { OptionCard } from "./OptionCard";
import { PlanDiffConfirmation } from "./PlanDiffConfirmation";
import { SelectionActions } from "./SelectionActions";
import { rootToSlug } from "../workbench/projectSlug";
import type { NotebookInteractionMode } from "./notebookApi";
import {
  type NotebookExecutionResult,
  type NotebookOptionRevision,
  type NotebookSelection,
  type NotebookSelectionAnchor,
  type NotebookView,
  type PendingConfirmation,
} from "./contracts";
import type { DomainMemoryCandidate, DomainMemoryPreferences } from "./domainMemoryContracts";

/**
 * The Notebook surface: a narrative stream, persisted option batches, the
 * confirmation step, and the visible slice. Plan mode caps a batch at three
 * options, while Action mode verifies one requested path; the Notebook must
 * still show older batches and deferred siblings so navigation never turns
 * persisted analysis history into an apparent deletion.
 *
 * Six states have to be distinguishable at a glance — loading, error, empty,
 * pending, confirmation, success — because five of them are routinely rendered
 * as the sixth. A run that is still executing is not a result; a run that
 * finished but failed its artifact contract is not a result either (spec §5.3),
 * and this surface refuses to print one.
 */

export interface NotebookSurfaceProps {
  view: NotebookView;
  projectRoot?: string;
  busy?: boolean;
  planning?: boolean;
  planningError?: { code: string; message: string } | null;
  actionError?: { code: string; message: string } | null;
  selectionAnchor?: NotebookSelectionAnchor | null;
  onDismissSelection?: () => void;
  onTextSelection?: (
    selection: NotebookSelection,
    anchor: NotebookSelectionAnchor,
  ) => void;
  onSelectOption?: (option: NotebookOptionRevision) => void;
  onDeferOption?: (option: NotebookOptionRevision) => void;
  onRejectOption?: (option: NotebookOptionRevision) => void;
  onRevalidateOption?: (option: NotebookOptionRevision) => void;
  onReplan?: () => void;
  onStartNewAnalysis?: () => void;
  newAnalysisDisabled?: boolean;
  interactionMode?: NotebookInteractionMode;
  onInteractionModeChange?: (mode: NotebookInteractionMode) => void;
  userIntent?: string;
  onUserIntent?: (goal: string) => void;
  onCancelPlanning?: () => void;
  /** Server-published total planning budget, shown while a pass runs. */
  planningDeadlineSeconds?: number;
  /** Epoch ms the in-flight planning attempt began, when one is running. */
  planningStartedAtMs?: number;
  onConfirm?: (confirmation: PendingConfirmation) => void;
  onCancelConfirmation?: (confirmation: PendingConfirmation) => void;
  onConfirmAndExecute?: (option: NotebookOptionRevision) => void;
  onSelectionAsk?: (selection: NotebookSelection) => void;
  onSelectionExplain?: (selection: NotebookSelection) => void;
  onSelectionFollowUp?: (selection: NotebookSelection) => void;
  onSelectionSaveNote?: (selection: NotebookSelection) => void;
  onSelectionDefer?: (selection: NotebookSelection) => void;
  domainMemoryPreferences?: DomainMemoryPreferences;
  onDomainMemoryPreferencesChange?: (preferences: DomainMemoryPreferences) => void;
  domainMemoryCandidates?: DomainMemoryCandidate[];
  onDomainMemoryCandidateReview?: (
    candidateId: string,
    decision: "approved" | "rejected",
    revision: number,
  ) => void;
}

function exclusionSummary(reasons: Record<string, number>): string {
  return Object.entries(reasons)
    .map(([reason, count]) => `${reason} ${count}`)
    .join(", ");
}

const MAX_VISIBLE_EXECUTION_ISSUES = 8;

function NotebookPlanningProgress({
  onCancel,
  deadlineSeconds,
  startedAtMs,
}: {
  onCancel?: () => void;
  /** Server-published total planning budget, when known. */
  deadlineSeconds?: number;
  /**
   * Epoch ms the attempt began. Mount time is not a usable substitute: this
   * surface remounts while the same request is still in flight, and anchoring
   * to the mount restarts the count at zero — which, next to a budget the
   * attempt has already been spending, understates how long it has run.
   */
  startedAtMs?: number;
}) {
  const anchorRef = useRef<number>(startedAtMs ?? Date.now());
  if (typeof startedAtMs === "number") anchorRef.current = startedAtMs;
  const anchor = anchorRef.current;
  const [elapsedSeconds, setElapsedSeconds] = useState(() =>
    Math.max(0, Math.floor((Date.now() - anchor) / 1000)),
  );

  useEffect(() => {
    setElapsedSeconds(Math.max(0, Math.floor((Date.now() - anchor) / 1000)));
    const timer = window.setInterval(() => {
      setElapsedSeconds(Math.max(0, Math.floor((Date.now() - anchor) / 1000)));
    }, 1_000);
    return () => window.clearInterval(timer);
  }, [anchor]);

  // An elapsed counter alone cannot distinguish a pass that is still inside its
  // budget from one that has hung, which left cancellation as the only recourse
  // on screen. Show the budget when the server published one.
  const hasDeadline = typeof deadlineSeconds === "number" && deadlineSeconds > 0;
  const overdue = hasDeadline && elapsedSeconds > (deadlineSeconds as number);
  const elapsedLabel = hasDeadline
    ? `Elapsed ${elapsedSeconds}s / ${deadlineSeconds}s`
    : `Elapsed ${elapsedSeconds}s`;

  return (
    <section
      className="nb-planning-progress"
      data-testid="notebook-planning-progress"
      data-overdue={overdue ? "true" : undefined}
      aria-live="polite"
    >
      <header>
        <span className="nb-label">How the plan is being formed</span>
        <span data-testid="notebook-planning-elapsed">
          {overdue
            ? `${elapsedLabel} — past the planning budget; the server is ending it`
            : elapsedLabel}
        </span>
      </header>
      <ol>
        <li data-status="completed">Bounded Notebook context compiled</li>
        <li data-status="active">Agent and bounded evidence inspections are running</li>
        <li data-status="pending">Validating evidence-bound options</li>
      </ol>
      <p>
        Live, auditable Workbench stages and evidence checks. Private chain-of-thought is
        not exposed; a provider summary requires an explicitly supported field.
      </p>
      {onCancel ? (
        <button
          type="button"
          className="nb-button"
          data-testid="notebook-cancel-planning"
          onClick={onCancel}
        >
          Cancel
        </button>
      ) : null}
    </section>
  );
}

export function NotebookSurface(props: NotebookSurfaceProps) {
  const { view } = props;
  const interactionMode = props.interactionMode ?? "plan";
  const actionMode = interactionMode === "action";
  const [intentDraft, setIntentDraft] = useState(props.userIntent ?? "");
  const [newAnalysisOpen, setNewAnalysisOpen] = useState(false);
  const confirmationSlotRef = useRef<HTMLDivElement>(null);
  const confirmationKey =
    view.status === "ready" && view.notebook.confirmation
      ? `${view.notebook.confirmation.option.option_id}:${view.notebook.confirmation.option.option_revision}`
      : null;

  useEffect(() => {
    if (!confirmationKey) return;
    const slot = confirmationSlotRef.current;
    if (!slot) return;
    slot.focus({ preventScroll: true });
    slot.scrollIntoView?.({ behavior: "smooth", block: "center" });
  }, [confirmationKey]);

  useEffect(() => {
    setIntentDraft(props.userIntent ?? "");
  }, [props.userIntent]);

  function captureTextSelection(event: React.MouseEvent<HTMLDivElement>) {
    const browserSelection = window.getSelection();
    const selected = browserSelection?.toString().trim() ?? "";
    if (!selected) return;
    const target = event.target as HTMLElement | null;
    const narrative = target?.closest<HTMLElement>('[data-testid^="narrative-"]');
    if (!narrative) return;
    const testId = narrative.dataset.testid;
    if (!testId) return;
    const entryId = testId.replace(/^narrative-/, "");
    const kind = narrative.dataset.kind ?? "notebook";
    const sourceLabel = kind === "agent" ? `agent message ${entryId}` : `${kind} entry ${entryId}`;
    const range = browserSelection && browserSelection.rangeCount > 0
      ? browserSelection.getRangeAt(0)
      : null;
    const rangeRect = range?.getBoundingClientRect();
    const targetRect = narrative.getBoundingClientRect();
    props.onTextSelection?.(
      {
        text: selected,
        source_label: sourceLabel,
        source_ref: `narrative:${entryId}`,
      },
      {
        top: (rangeRect?.bottom || targetRect.bottom) + 8,
        left: rangeRect?.left || targetRect.left,
      },
    );
  }

  if (view.status === "loading") {
    const loadingMessage = view.phase === "planning"
      ? "Planning analysis options with the agent…"
      : "Compiling the bounded notebook context…";
    return (
      <div className="nb-surface" data-testid="notebook-surface" data-state="loading">
        <p data-testid="notebook-loading" data-phase={view.phase ?? "compiling"}>
          {loadingMessage}
        </p>
        {view.phase === "planning" ? (
          <NotebookPlanningProgress
            onCancel={props.onCancelPlanning}
            deadlineSeconds={props.planningDeadlineSeconds}
            startedAtMs={props.planningStartedAtMs}
          />
        ) : null}
      </div>
    );
  }

  if (view.status === "error") {
    const canReplan = props.onReplan && (
      view.error.code === "OPTION_MATERIALIZATION_FAILED" ||
      view.error.code === "GENESIS_MODEL_INCOMPLETE" ||
      view.error.code === "GENESIS_MODEL_EVIDENCE_REQUIRED" ||
      view.error.code === "NOTEBOOK_PLANNING_CONTRACT_INVALID" ||
      view.error.code === "NOTEBOOK_PLANNING_TIMEOUT" ||
      view.error.code === "NOTEBOOK_PLANNING_CANCELLED"
    );
    return (
      <div className="nb-surface" data-testid="notebook-surface" data-state="error">
        <div className="nb-error" data-testid="notebook-error" role="alert">
          <span className="nb-error-code">{view.error.code}</span>
          <p className="nb-error-message">{view.error.message}</p>
          {canReplan ? (
            <button
              type="button"
            className="nb-button nb-button-primary"
              data-testid="notebook-replan-options"
              onClick={props.onReplan}
            >
              {actionMode ? "Recheck request" : "Replan with current evidence"}
            </button>
          ) : null}
        </div>
      </div>
    );
  }

  const notebook = view.notebook;
  const batches = Array.from(
    notebook.options.reduce((groups, option) => {
      const batch = groups.get(option.batch_id) ?? [];
      batch.push(option);
      groups.set(option.batch_id, batch);
      return groups;
    }, new Map<string, NotebookOptionRevision[]>()),
  ).sort(([, left], [, right]) => {
    const leftCreatedAt = Math.max(
      ...left.map((option) => Date.parse(option.created_at)),
    );
    const rightCreatedAt = Math.max(
      ...right.map((option) => Date.parse(option.created_at)),
    );
    return leftCreatedAt - rightCreatedAt;
  });
  const currentBatchId =
    batches.length > 0 ? batches[batches.length - 1][0] : null;
  const executing = notebook.options.find((option) => option.lifecycle_status === "executing");
  const outcome = notebook.outcome ?? null;
  const executionResults = Object.values(notebook.executionResults ?? {});
  const contractFailed = outcome !== null && outcome.validation_status === "failed";
  const genericCommittedResults = executionResults.filter(
    (result) =>
      result.committed &&
      result.execution_status === "succeeded" &&
      result.artifact_validation.validation_status !== "failed",
  );
  const showSuccess =
    !contractFailed && (notebook.result !== null || genericCommittedResults.length > 0);

  const state = notebook.confirmation
    ? "confirmation"
    : executing
      ? "pending"
      : showSuccess
        ? "success"
        : notebook.options.length === 0
          ? "empty"
          : "ready";

  return (
    <div
      className="nb-surface"
      data-testid="notebook-surface"
      data-state={state}
      onPointerDown={(event) => {
        const target = event.target as HTMLElement | null;
        if (!target?.closest('[data-testid="notebook-new-analysis-actions"]')) {
          setNewAnalysisOpen(false);
        }
        if (!target?.closest('[data-testid="notebook-selection-actions"]')) {
          props.onDismissSelection?.();
        }
      }}
      onMouseUp={captureTextSelection}
    >
      <header className="nb-surface-header">
        <div className="nb-surface-header-title">
          <span className="nb-label">Notebook</span>
          <span>{`${notebook.notebook_id} · ${notebook.run_family_id}`}</span>
        </div>
        {props.onStartNewAnalysis ? (
          <div className="nb-notebook-new-analysis" data-testid="notebook-new-analysis-actions">
            <button
              type="button"
              className="nb-button nb-notebook-new-analysis-trigger"
              data-testid="notebook-new-analysis-menu"
              aria-expanded={newAnalysisOpen}
              aria-haspopup="menu"
              disabled={props.newAnalysisDisabled}
              onClick={() => setNewAnalysisOpen((open) => !open)}
            >
              New analysis <span aria-hidden="true">▾</span>
            </button>
            {newAnalysisOpen ? (
              <div className="nb-notebook-new-analysis-popover" role="menu">
                <p>Creates a separate Notebook. The current analysis is unchanged.</p>
                <button
                  type="button"
                  className="nb-button"
                  data-testid="notebook-start-from-source"
                  role="menuitem"
                  disabled={props.newAnalysisDisabled}
                  onClick={() => {
                    setNewAnalysisOpen(false);
                    props.onStartNewAnalysis?.();
                  }}
                >
                  Start from source data
                </button>
              </div>
            ) : null}
          </div>
        ) : null}
      </header>

      <form
        className="nb-user-intent"
        data-testid="notebook-user-intent"
        onSubmit={(event) => {
          event.preventDefault();
          const goal = intentDraft.trim();
          if (goal) props.onUserIntent?.(goal);
        }}
      >
        <div className="nb-interaction-mode" role="group" aria-label="Notebook mode">
          <button
            type="button"
            className="nb-interaction-mode-button"
            data-testid="notebook-mode-plan"
            aria-pressed={!actionMode}
            disabled={props.planning || props.busy}
            onClick={() => props.onInteractionModeChange?.("plan")}
          >
            Plan
          </button>
          <button
            type="button"
            className="nb-interaction-mode-button"
            data-testid="notebook-mode-action"
            aria-pressed={actionMode}
            disabled={props.planning || props.busy}
            onClick={() => props.onInteractionModeChange?.("action")}
          >
            Action
          </button>
        </div>
        <p className="nb-interaction-mode-help">
          {actionMode
            ? "Check a specified analysis and prepare one editable Draft. Nothing runs until you confirm."
            : "Explore evidence-backed analysis paths before choosing one Draft. Nothing runs until you confirm."}
        </p>
        <label htmlFor="notebook-user-intent-input">
          {actionMode ? "What should Workbench do?" : "What do you want to find out?"}
        </label>
        <textarea
          id="notebook-user-intent-input"
          data-testid="notebook-user-intent-input"
          value={intentDraft}
          rows={3}
          placeholder={actionMode
            ? "Describe the analysis specification, variables, constraints, and required outputs."
            : "Describe the research question, outcome, constraints, and the comparison you need."}
          onChange={(event) => setIntentDraft(event.target.value)}
        />
        <button
          type="submit"
          className="nb-button nb-button-primary"
          data-testid="notebook-submit-intent"
          disabled={!intentDraft.trim() || props.planning}
        >
          {actionMode
            ? props.userIntent ? "Update and prepare Draft" : "Check and prepare Draft"
            : props.userIntent ? "Update goal and replan" : "Plan analysis"}
        </button>
      </form>

      {props.domainMemoryPreferences && props.onDomainMemoryPreferencesChange ? (
        <DomainMemoryControls
          preferences={props.domainMemoryPreferences}
          onChange={props.onDomainMemoryPreferencesChange}
        />
      ) : null}

      {props.planning ? (
        <NotebookPlanningProgress
            onCancel={props.onCancelPlanning}
            deadlineSeconds={props.planningDeadlineSeconds}
            startedAtMs={props.planningStartedAtMs}
          />
      ) : null}

      {props.planningError ? (
        <div
          className="nb-planning-error"
          data-testid="notebook-planning-error"
          role="status"
        >
          <span className="nb-error-code">{props.planningError.code}</span>
          <span>{props.planningError.message}</span>
          {props.onReplan ? (
            <button
              type="button"
              className="nb-button"
              data-testid="notebook-retry-planning"
              onClick={props.onReplan}
            >
              Retry
            </button>
          ) : null}
        </div>
      ) : null}

      {props.actionError ? (
        <div
          className="nb-action-error"
          data-testid="notebook-action-error"
          role="alert"
        >
          <span className="nb-error-code">{props.actionError.code}</span>
          <span>{props.actionError.message}</span>
        </div>
      ) : null}

      <section className="nb-narrative" data-testid="notebook-narrative">
        {notebook.narrative.map((entry) => (
          <p
            key={entry.entry_id}
            className="nb-narrative-entry"
            data-testid={`narrative-${entry.entry_id}`}
            data-kind={entry.kind}
          >
            <span className="nb-narrative-kind">{`${entry.kind} · `}</span>
            <span>{entry.text}</span>
          </p>
        ))}
      </section>

      <SelectionActions
        selection={notebook.selection}
        anchor={props.selectionAnchor}
        onAddToTask={props.onSelectionAsk}
        onMoreDetails={props.onSelectionExplain}
        onAskInSideChat={props.onSelectionFollowUp}
        onAsk={props.onSelectionAsk}
        onExplain={props.onSelectionExplain}
        onFollowUp={props.onSelectionFollowUp}
        onSaveNote={props.onSelectionSaveNote}
        onDeferAsOption={props.onSelectionDefer}
      />

      {notebook.materialization ? (
        <section className="nb-draft-handoff" data-testid="notebook-draft-handoff">
          {(() => {
            const execution = executionResults.find(
              (result) => result.option_id === notebook.materialization?.option_id,
            );
            return (
              <>
                <span className="nb-label">
                  {execution ? "Draft executed" : "Draft prepared"}
                </span>
                {execution?.run_id ? <p>{`run ${execution.run_id}`}</p> : null}
              </>
            );
          })()}
          <p>{`${notebook.materialization.draft_execution_mode} · ${notebook.materialization.draft_id}`}</p>
          <code>{notebook.materialization.draft_hash}</code>
          {props.projectRoot ? (
            <a
              href={(() => {
                const nodeKey = notebook.materialization.draft_execution_mode === "genesis"
                  ? `draft:${notebook.materialization.draft_id}:model_1`
                  : `draft:${notebook.materialization.draft_id}`;
                const params = new URLSearchParams({
                  view: "graph",
                  notebook: notebook.notebook_id,
                  panel: "agent",
                  tabs: nodeKey,
                  active: nodeKey,
                  focus: nodeKey,
                });
                return `/p/${rootToSlug(props.projectRoot)}/graph?${params.toString()}`;
              })()}
            >
              Open Draft in Graph
            </a>
          ) : null}
        </section>
      ) : null}

      {executing ? (
        <p className="nb-pending" data-testid="notebook-pending">
          {`Executing ${executing.option_id} rev ${executing.option_revision} as ${
            notebook.execution?.run_id ?? "an unassigned run"
          } — no result yet`}
        </p>
      ) : null}

      {contractFailed && outcome ? (
        <div className="nb-contract-failure" data-testid="notebook-contract-failure" role="alert">
          <span>
            {`execution ${outcome.execution_status} · output contract failed — this is not a result`}
          </span>
          <ul>
            {outcome.observed
              .filter((item) => !item.satisfied)
              .map((item) => (
                <li key={item.artifact_id}>
                  {`${item.artifact_id} · observed ${item.observed_count}${
                    item.issue_code ? ` · ${item.issue_code}` : ""
                  }`}
                </li>
              ))}
          </ul>
        </div>
      ) : null}

      {showSuccess && notebook.result ? (
        <section className="nb-success" data-testid="notebook-success">
          <span className="nb-label">Executed result</span>
          <ul>
            <li>{`${notebook.result.specification.canonical} on ${notebook.result.endog}`}</li>
            <li>{`n_obs ${notebook.result.n_obs} · excluded ${notebook.result.n_excluded} (${exclusionSummary(
              notebook.result.exclusion_reasons,
            )})`}</li>
            <li>{`AIC ${notebook.result.aic} · BIC ${notebook.result.bic} · logL ${notebook.result.log_likelihood}`}</li>
            <li>{`${notebook.result.fit_method} · ${notebook.result.convergence_code}`}</li>
            <li>{`run ${notebook.execution?.run_id ?? "unrecorded"}`}</li>
            <li className="nb-success-identity">{notebook.result.result_identity}</li>
          </ul>
        </section>
      ) : null}

      {executionResults.length > 0 ? (
        <section className="nb-success" data-testid="notebook-execution-summary">
          <span className="nb-label">Executed analysis</span>
          {executionResults.map((result: NotebookExecutionResult) => (
            <article key={`${result.option_id}:${result.option_revision}`}>
              <p>
                {result.workflow_execution
                  ? `${result.option_id} rev ${result.option_revision} · ${result.workflow_execution.branch_runs.length} model branches · no single active head`
                  : `${result.option_id} rev ${result.option_revision} · run ${result.run_id ?? "unassigned"}`}
              </p>
              <p>{`execution ${result.execution_status} · output contract ${result.artifact_validation.validation_status}`}</p>
              {result.workflow_execution ? (
                <p>{`workflow ${result.workflow_execution.status} · ${result.workflow_execution.post_estimation_artifact_ids.length} post-estimation artifact${result.workflow_execution.post_estimation_artifact_ids.length === 1 ? "" : "s"}`}</p>
              ) : null}
              <p>{`Committed ${result.committed ? "yes" : "no"}. Checked: ${result.artifact_validation.checked_dimensions.join(
                ", ",
              )}. Not checked: ${result.artifact_validation.not_evaluated_dimensions.join(
                ", ",
              )}.`}</p>
              {result.artifact_validation.issues.length > 0 ? (
                <ul>
                  {result.artifact_validation.issues
                    .slice(0, MAX_VISIBLE_EXECUTION_ISSUES)
                    .map((issue) => (
                    <li key={`${issue.code}:${issue.artifact_id}`}>
                      {`${issue.artifact_id} · ${issue.code} · ${issue.detail}`}
                    </li>
                    ))}
                  {result.artifact_validation.issues.length +
                    (result.artifact_validation.omitted_issue_count ?? 0) >
                  MAX_VISIBLE_EXECUTION_ISSUES ? (
                    <li>
                      {`${Math.max(
                        0,
                        result.artifact_validation.issues.length +
                          (result.artifact_validation.omitted_issue_count ?? 0) -
                          MAX_VISIBLE_EXECUTION_ISSUES,
                      )} additional artifact notes omitted from this bounded Notebook view; inspect the Run artifacts for the complete manifest.`}
                    </li>
                  ) : null}
                </ul>
              ) : null}
            </article>
          ))}
        </section>
      ) : null}

      {notebook.options.length === 0 ? (
        <p className="nb-empty" data-testid="notebook-empty">
          No analysis options for this context yet — the agent has not proposed one.
        </p>
      ) : (
        <section className="nb-option-list" data-testid="notebook-option-list">
          {batches.map(([batchId, options]) => {
            const isCurrentBatch = batchId === currentBatchId;
            const isHistoricalStaleBatch =
              !isCurrentBatch &&
              options.every((option) => option.freshness_status === "stale");
            return (
            <details
              className="nb-option-batch"
              data-testid={`notebook-option-batch-${batchId}`}
              key={batchId}
              open={!isHistoricalStaleBatch}
            >
              <summary className="nb-option-batch-header">
                <span className="nb-label">
                  {isCurrentBatch ? "Current option batch" : "Previous option batch"}
                </span>
                <code>{batchId}</code>
                <span>
                  {`${options.length} persisted option${options.length === 1 ? "" : "s"}${
                    isHistoricalStaleBatch ? " · stale history" : ""
                  }`}
                </span>
                <span className="nb-option-batch-action">Show / hide</span>
              </summary>
              <div className="nb-option-batch-body">
                {options.map((option) => (
                  <Fragment key={option.option_id}>
                    <OptionCard
                      option={option}
                      interactionMode={props.interactionMode ?? "plan"}
                      outcome={outcome && outcome.observed.length > 0 ? outcome : null}
                      onSelect={props.onSelectOption}
                      onDefer={props.onDeferOption}
                      onReject={props.onRejectOption}
                      onRevalidate={props.onRevalidateOption}
                      onConfirmAndExecute={props.onConfirmAndExecute}
                    />
                    {notebook.confirmation?.option.option_id === option.option_id ? (
                      <div
                        ref={confirmationSlotRef}
                        data-testid="notebook-confirmation-slot"
                        tabIndex={-1}
                      >
                        <PlanDiffConfirmation
                          confirmation={notebook.confirmation}
                          busy={props.busy}
                          onConfirm={props.onConfirm}
                          onCancel={props.onCancelConfirmation}
                        />
                      </div>
                    ) : null}
                  </Fragment>
                ))}
              </div>
            </details>
            );
          })}
        </section>
      )}

      {notebook.contextSlice ? <ContextSlicePanel slice={notebook.contextSlice} /> : null}

      {notebook.contextSlice?.domain_memory_projection ? (
        <DomainMemoryEntryList projection={notebook.contextSlice.domain_memory_projection} />
      ) : null}
      {props.domainMemoryCandidates && props.onDomainMemoryCandidateReview ? (
        <DomainMemoryReviewQueue
          candidates={props.domainMemoryCandidates}
          onReview={props.onDomainMemoryCandidateReview}
        />
      ) : null}
    </div>
  );
}
