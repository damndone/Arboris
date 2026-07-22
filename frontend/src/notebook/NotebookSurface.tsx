import "./notebook.css";
import { ContextSlicePanel } from "./ContextSlicePanel";
import { OptionCard } from "./OptionCard";
import { PlanDiffConfirmation } from "./PlanDiffConfirmation";
import { SelectionActions } from "./SelectionActions";
import {
  MAX_OPTIONS_PER_BATCH,
  type NotebookOptionRevision,
  type NotebookSelection,
  type NotebookView,
  type PendingConfirmation,
} from "./contracts";

/**
 * The Notebook surface: a narrative stream, at most three option cards, the
 * confirmation step, and the visible slice.
 *
 * Six states have to be distinguishable at a glance — loading, error, empty,
 * pending, confirmation, success — because five of them are routinely rendered
 * as the sixth. A run that is still executing is not a result; a run that
 * finished but failed its artifact contract is not a result either (spec §5.3),
 * and this surface refuses to print one.
 */

export interface NotebookSurfaceProps {
  view: NotebookView;
  onSelectOption?: (option: NotebookOptionRevision) => void;
  onDeferOption?: (option: NotebookOptionRevision) => void;
  onRejectOption?: (option: NotebookOptionRevision) => void;
  onRevalidateOption?: (option: NotebookOptionRevision) => void;
  onConfirm?: (confirmation: PendingConfirmation) => void;
  onCancelConfirmation?: (confirmation: PendingConfirmation) => void;
  onSelectionAsk?: (selection: NotebookSelection) => void;
  onSelectionExplain?: (selection: NotebookSelection) => void;
  onSelectionFollowUp?: (selection: NotebookSelection) => void;
  onSelectionSaveNote?: (selection: NotebookSelection) => void;
  onSelectionDefer?: (selection: NotebookSelection) => void;
}

function exclusionSummary(reasons: Record<string, number>): string {
  return Object.entries(reasons)
    .map(([reason, count]) => `${reason} ${count}`)
    .join(", ");
}

export function NotebookSurface(props: NotebookSurfaceProps) {
  const { view } = props;

  if (view.status === "loading") {
    return (
      <div className="nb-surface" data-testid="notebook-surface" data-state="loading">
        <p data-testid="notebook-loading">Compiling the bounded notebook context…</p>
      </div>
    );
  }

  if (view.status === "error") {
    return (
      <div className="nb-surface" data-testid="notebook-surface" data-state="error">
        <div className="nb-error" data-testid="notebook-error" role="alert">
          <span className="nb-error-code">{view.error.code}</span>
          <p className="nb-error-message">{view.error.message}</p>
        </div>
      </div>
    );
  }

  const notebook = view.notebook;
  const shown = notebook.options.slice(0, MAX_OPTIONS_PER_BATCH);
  const overflow = notebook.options.length - shown.length;
  const executing = notebook.options.find((option) => option.lifecycle_status === "executing");
  const outcome = notebook.outcome ?? null;
  const contractFailed = outcome !== null && outcome.validation_status === "failed";
  const showSuccess = notebook.result !== null && !contractFailed;

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
    <div className="nb-surface" data-testid="notebook-surface" data-state={state}>
      <header className="nb-surface-header">
        <span className="nb-label">Notebook</span>
        <span>{`${notebook.notebook_id} · ${notebook.run_family_id}`}</span>
      </header>

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
        onAsk={props.onSelectionAsk}
        onExplain={props.onSelectionExplain}
        onFollowUp={props.onSelectionFollowUp}
        onSaveNote={props.onSelectionSaveNote}
        onDeferAsOption={props.onSelectionDefer}
      />

      {notebook.confirmation ? (
        <PlanDiffConfirmation
          confirmation={notebook.confirmation}
          onConfirm={props.onConfirm}
          onCancel={props.onCancelConfirmation}
        />
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

      {notebook.options.length === 0 ? (
        <p className="nb-empty" data-testid="notebook-empty">
          No analysis options for this context yet — the agent has not proposed one.
        </p>
      ) : (
        <section className="nb-option-list" data-testid="notebook-option-list">
          {shown.map((option) => (
            <OptionCard
              key={option.option_id}
              option={option}
              outcome={outcome && outcome.observed.length > 0 ? outcome : null}
              onSelect={props.onSelectOption}
              onDefer={props.onDeferOption}
              onReject={props.onRejectOption}
              onRevalidate={props.onRevalidateOption}
            />
          ))}
          {overflow > 0 ? (
            <p className="nb-option-overflow" data-testid="notebook-option-overflow">
              {`${overflow} option${overflow === 1 ? "" : "s"} beyond the ${MAX_OPTIONS_PER_BATCH}-option limit ${
                overflow === 1 ? "is" : "are"
              } not shown.`}
            </p>
          ) : null}
        </section>
      )}

      {notebook.contextSlice ? <ContextSlicePanel slice={notebook.contextSlice} /> : null}
    </div>
  );
}
