import type { ArtifactContractOutcome, NotebookOptionRevision } from "./contracts";
import { axisNote, executability, recommendationLabel } from "./statusAxes";

export interface OptionCardProps {
  option: NotebookOptionRevision;
  /** Backend verdict after execution. The UI never derives this. */
  outcome?: ArtifactContractOutcome | null;
  onSelect?: (option: NotebookOptionRevision) => void;
  onDefer?: (option: NotebookOptionRevision) => void;
  onReject?: (option: NotebookOptionRevision) => void;
  onRevalidate?: (option: NotebookOptionRevision) => void;
  onConfirmAndExecute?: (option: NotebookOptionRevision) => void;
}

function Axis({
  axis,
  value,
  note,
}: {
  axis: string;
  value: string;
  note: string | null;
}) {
  return (
    <span
      className="nb-axis"
      data-testid={`option-axis-${axis}`}
      data-axis={axis}
      data-value={value}
    >
      <span className="nb-axis-name">{`${axis} ${value}`}</span>
      {note ? <span className="nb-axis-note">{` — ${note}`}</span> : null}
    </span>
  );
}

const RISK_LABELS = {
  low: "Low risk",
  medium: "Medium risk",
  high: "High risk",
} as const;

export function OptionCard({
  option,
  outcome = null,
  onSelect,
  onDefer,
  onReject,
  onRevalidate,
  onConfirmAndExecute,
}: OptionCardProps) {
  const gate = executability(option);
  const notes = axisNote(option);
  const contract = option.artifact_contract;
  const experimental = option.experimentalExecution === true;
  const expectedById = new Map(contract.expected.map((item) => [item.artifact_id, item]));

  return (
    <article
      className="nb-option-card"
      data-testid={`option-card-${option.option_id}`}
      data-recommended={option.recommendation_status === "recommended" ? "true" : "false"}
      data-lifecycle={option.lifecycle_status}
      data-freshness={option.freshness_status}
      data-validation={option.validation_status}
    >
      <header className="nb-option-header">
        <span className="nb-option-rank" data-testid="option-rank">
          {recommendationLabel(option)}
        </span>
        <span
          className="nb-option-risk"
          data-testid="option-risk"
          data-risk={option.risk_level}
        >
          {RISK_LABELS[option.risk_level]}
        </span>
      </header>

      <div className="nb-option-axes">
        <Axis axis="lifecycle" value={option.lifecycle_status} note={notes.lifecycle} />
        <Axis axis="freshness" value={option.freshness_status} note={notes.freshness} />
        <Axis axis="validation" value={option.validation_status} note={notes.validation} />
      </div>

      <p className="nb-option-rationale" data-testid="option-rationale">
        {option.rationale}
      </p>

      <div className="nb-option-assumptions" data-testid="option-assumptions">
        <span className="nb-label">Assumptions</span>
        <ul>
          {option.assumptions.map((assumption) => (
            <li key={assumption}>{assumption}</li>
          ))}
        </ul>
      </div>

      <div className="nb-option-pins" data-testid="option-pins">
        <span>{`option ${option.option_id} rev ${option.option_revision}`}</span>
        <span>{` · proposal ${option.typed_proposal_id} rev ${option.typed_proposal_revision}`}</span>
        <span>{` · context ${option.generation_context_id}`}</span>
        {option.supersedes_option_revision !== null ? (
          <span>{` · supersedes rev ${option.supersedes_option_revision}`}</span>
        ) : null}
      </div>

      <section className="nb-option-contract">
        <span className="nb-label">Expected artifacts</span>
        <ul>
          {contract.expected.map((item) => (
            <li key={item.artifact_id} data-testid={`option-expected-${item.artifact_id}`}>
              {`${item.artifact_id} · ${item.artifact_type} · ${
                item.required ? "required" : "optional"
              } · count ${item.count}${item.step ? ` · step ${item.step}` : ""}`}
            </li>
          ))}
        </ul>
        <p className="nb-option-dimensions" data-testid="option-contract-dimensions">
          {`Checked: ${contract.checked_dimensions.join(", ")}`}
          <br />
          {`Not checked: ${contract.not_evaluated_dimensions.join(", ")}`}
        </p>
      </section>

      {option.capability_resolution_binding_ref ? (
        <p data-testid="option-capability-binding" className="nb-option-capability-binding">
          {experimental
            ? "server-bound experimental capability · high risk · explicit confirmation required"
            : option.confirmAndExecute
            ? "server-bound capability · explicit confirmation required"
            : "server-bound capability · materialization only until execution gates are satisfied"}
        </p>
      ) : null}

      {outcome ? (
        <section className="nb-option-outcome" data-testid="option-contract-outcome">
          <span className="nb-outcome-headline">
            {`execution ${outcome.execution_status} · output contract ${outcome.validation_status}`}
          </span>
          <ul>
            {outcome.observed.map((observed) => {
              const expected = expectedById.get(observed.artifact_id);
              return (
                <li
                  key={observed.artifact_id}
                  data-testid={`option-observed-${observed.artifact_id}`}
                >
                  {`${observed.artifact_id} · expected ${
                    expected ? expected.count : "not declared"
                  } · observed ${observed.observed_count} · ${
                    observed.satisfied ? "satisfied" : "not satisfied"
                  }${observed.issue_code ? ` · ${observed.issue_code}` : ""}`}
                </li>
              );
            })}
          </ul>
          <p className="nb-outcome-scope">
            {`Verified against ${outcome.validation_profile}. Checked: ${outcome.checked_dimensions.join(
              ", ",
            )}. Not checked: ${outcome.not_evaluated_dimensions.join(", ")}.`}
          </p>
        </section>
      ) : null}

      {gate.blockedReason ? (
        <p className="nb-option-blocked" data-testid="option-blocked-reason">
          {gate.blockedReason}
        </p>
      ) : null}

      <footer className="nb-option-actions">
        <button
          type="button"
          data-testid="option-execute"
          className="nb-button nb-button-primary"
          disabled={!gate.executable}
          onClick={() => onSelect?.(option)}
        >
          {option.lifecycle_status === "executed"
            ? "Already executed"
            : "Review plan"}
        </button>
        {option.confirmAndExecute ? (
          <button
            type="button"
            data-testid="option-confirm-and-execute"
            className="nb-button nb-button-primary"
          disabled={!gate.executable}
          onClick={() => onConfirmAndExecute?.(option)}
        >
          {experimental ? "Confirm experimental execution" : "Confirm and execute"}
        </button>
        ) : null}
        <button
          type="button"
          data-testid="option-revalidate"
          className="nb-button"
          disabled={!gate.needsRevalidation}
          onClick={() => onRevalidate?.(option)}
        >
          Request revalidation
        </button>
        <button
          type="button"
          data-testid="option-defer"
          className="nb-button"
          onClick={() => onDefer?.(option)}
        >
          Defer
        </button>
        <button
          type="button"
          data-testid="option-reject"
          className="nb-button"
          onClick={() => onReject?.(option)}
        >
          Reject
        </button>
      </footer>
    </article>
  );
}
