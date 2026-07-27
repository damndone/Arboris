import type { PendingConfirmation } from "./contracts";

/**
 * The confirmation step (spec §3.3): what changes, what it will produce, and
 * exactly which revisions are pinned.
 *
 * The pins matter more than they look. A user who reads revision 2 and confirms
 * must execute revision 2 — if the agent produced revision 3 in between, the
 * execution packet still names 2, and the surface shows which one is being run.
 */

export interface PlanDiffConfirmationProps {
  confirmation: PendingConfirmation;
  busy?: boolean;
  onConfirm?: (confirmation: PendingConfirmation) => void;
  onCancel?: (confirmation: PendingConfirmation) => void;
}

export function PlanDiffConfirmation({
  confirmation,
  busy = false,
  onConfirm,
  onCancel,
}: PlanDiffConfirmationProps) {
  const { option, execution, plan_diff } = confirmation;
  const confirmAndExecute = confirmation.mode === "confirm_and_execute";
  const required = option.artifact_contract.expected.filter((item) => item.required);
  const optional = option.artifact_contract.expected.filter((item) => !item.required);

  return (
    <section className="nb-confirmation" data-testid="notebook-confirmation">
      <header className="nb-confirmation-header">
        <span className="nb-label">
          {confirmAndExecute
            ? "Confirm before dispatching capability"
            : option.materializable
              ? "Confirm before preparing Draft"
              : "Confirm before running"}
        </span>
        <span data-testid="confirmation-pins">
          {`${execution.option_id} rev ${execution.option_revision} · ${execution.proposal_id} rev ${execution.proposal_revision}`}
        </span>
      </header>

      <div className="nb-confirmation-diff" data-testid="confirmation-plan-diff">
        <span className="nb-label">Plan diff</span>
        <ul>
          {plan_diff.map((line) => (
            <li key={line.field} data-testid={`plan-diff-${line.field}`}>
              {`${line.field}: ${line.from ?? "(unset)"} → ${line.to ?? "(unset)"}`}
            </li>
          ))}
        </ul>
      </div>

      <div className="nb-confirmation-expected" data-testid="confirmation-expected-artifacts">
        <span className="nb-label">This run must produce</span>
        <ul>
          {required.map((item) => (
            <li key={item.artifact_id}>
              {`${item.artifact_id} · ${item.artifact_type} · required${
                item.step ? ` · step ${item.step}` : ""
              }`}
            </li>
          ))}
        </ul>
        {optional.length > 0 ? (
          <>
            <span className="nb-label">May also produce</span>
            <ul>
              {optional.map((item) => (
                <li key={item.artifact_id}>
                  {`${item.artifact_id} · ${item.artifact_type} · optional${
                    item.step ? ` · step ${item.step}` : ""
                  }`}
                </li>
              ))}
            </ul>
          </>
        ) : null}
        <p className="nb-confirmation-scope">
          {`Checked on completion: ${option.artifact_contract.checked_dimensions.join(
            ", ",
          )}. Not checked: ${option.artifact_contract.not_evaluated_dimensions.join(", ")}.`}
        </p>
      </div>

      <footer className="nb-confirmation-actions">
        <button
          type="button"
          className="nb-button nb-button-primary"
          data-testid="confirmation-confirm"
          disabled={busy}
          onClick={() => onConfirm?.(confirmation)}
        >
          {busy
            ? "Submitting…"
            : confirmAndExecute
              ? "Confirm and execute"
              : option.materializable
              ? "Confirm and prepare Draft"
              : "Confirm and run"}
        </button>
        <button
          type="button"
          className="nb-button"
          data-testid="confirmation-cancel"
          disabled={busy}
          onClick={() => onCancel?.(confirmation)}
        >
          Cancel
        </button>
      </footer>
    </section>
  );
}
