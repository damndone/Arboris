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
 * confirmation step, and the visible slice. The planner caps each generated
 * batch at three options; the Notebook must still show older batches and
 * deferred siblings so navigation never turns persisted analysis history into
 * an apparent deletion.
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
  onCancelPlanning?: () => void;
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
}: {
  onCancel?: () => void;
}) {
  const [elapsedSeconds, setElapsedSeconds] = useState(0);

  useEffect(() => {
    const startedAt = Date.now();
    const timer = window.setInterval(() => {
      setElapsedSeconds(Math.floor((Date.now() - startedAt) / 1000));
    }, 1_000);
    return () => window.clearInterval(timer);
  }, []);

  return (
    <section
      className="nb-planning-progress"
      data-testid="notebook-planning-progress"
      aria-live="polite"
    >
      <header>
        <span className="nb-label">How the plan is being formed</span>
        <span data-testid="notebook-planning-elapsed">{`Elapsed ${elapsedSeconds}s`}</span>
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
          <NotebookPlanningProgress onCancel={props.onCancelPlanning} />
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
              Replan with current evidence
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
        if (!target?.closest('[data-testid="notebook-selection-actions"]')) {
          props.onDismissSelection?.();
        }
      }}
      onMouseUp={captureTextSelection}
    >
      <header className="nb-surface-header">
        <span className="nb-label">Notebook</span>
        <span>{`${notebook.notebook_id} · ${notebook.run_family_id}`}</span>
        {props.onReplan ? (
          <button
            type="button"
            className="nb-button"
            data-testid="notebook-replan-options"
            onClick={props.onReplan}
            disabled={props.busy}
          >
            Replan with current evidence
          </button>
        ) : null}
      </header>

      {props.domainMemoryPreferences && props.onDomainMemoryPreferencesChange ? (
        <DomainMemoryControls
          preferences={props.domainMemoryPreferences}
          onChange={props.onDomainMemoryPreferencesChange}
        />
      ) : null}

      {props.planning ? (
        <NotebookPlanningProgress onCancel={props.onCancelPlanning} />
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
              <p>{`${result.option_id} rev ${result.option_revision} · run ${result.run_id ?? "unassigned"}`}</p>
              <p>{`execution ${result.execution_status} · output contract ${result.artifact_validation.validation_status}`}</p>
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
