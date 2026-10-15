// v1.9.0 — what a preview promises and what a run produced. A preview lists
// its effects and risks and waits for Confirm; a finished run lists each step
// with its result, opened in place or in the workspace.

import { useState } from "react";
import { artifactUrl, readArtifact, type Operation, type Outcome } from "../manualApi";
import { ResultValue } from "./ResultValue";

const STATUS: Record<string, string> = {
  awaiting_confirmation: "Ready to run",
  completed: "Completed",
  partial: "Partly completed",
  failed: "Failed",
  running: "Running",
};

export const statusLabel = (status: string) => STATUS[status] ?? status.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());

function errorText(error: Outcome["error"]): string | null {
  if (!error) return null;
  const message = error.message ?? error.detail ?? error.code;
  return typeof message === "string" ? message : JSON.stringify(error);
}

type Shown = { key: string; value?: unknown; download?: string; error?: string };

export function OutcomeView({
  projectRoot,
  outcome,
  operations,
  busy,
  onConfirm,
  onOpenRun,
}: {
  projectRoot: string;
  outcome: Outcome;
  operations: Operation[];
  busy: boolean;
  onConfirm: () => void;
  onOpenRun: (runId: string) => void;
}) {
  const [shown, setShown] = useState<Shown | null>(null);
  const name = (id: string) => operations.find((op) => op.id === id)?.name ?? id.replace(/[._]/g, " ");
  const error = errorText(outcome.error);
  const show = async (run: string, id: string) => {
    const key = `${run}:${id}`;
    if (shown?.key === key) return setShown(null);
    try {
      const response = await readArtifact(projectRoot, run, id);
      setShown(
        response.headers.get("content-type")?.includes("json")
          ? { key, value: await response.json() }
          : { key, download: artifactUrl(projectRoot, run, id) },
      );
    } catch (reason) {
      setShown({ key, error: reason instanceof Error ? reason.message : String(reason) });
    }
  };

  return (
    <section className="op-outcome" aria-label="Analysis preview and results" data-status={outcome.status}>
      <h3 className="op-outcome__status">{statusLabel(outcome.status)}</h3>
      {outcome.expected_effect.length > 0 && (
        <ul className="op-outcome__effects">{outcome.expected_effect.map((line, i) => <li key={i}>{line}</li>)}</ul>
      )}
      {outcome.risks.length > 0 && (
        <ul className="op-outcome__risks" aria-label="Check before running">{outcome.risks.map((line, i) => <li key={i}>{line}</li>)}</ul>
      )}
      {error && <p role="alert">{error}</p>}
      {outcome.status === "awaiting_confirmation" && (
        <button type="button" className="op-primary" disabled={busy} onClick={onConfirm}>Confirm analysis</button>
      )}
      {outcome.steps.length > 0 && (
        <ol className="op-outcome__steps">
          {outcome.steps.map((step) => (
            <li key={step.step_id} data-status={step.status}>
              <div className="op-outcome__step">
                <span className="op-outcome__name">{name(step.operation_id)}</span>
                <span className="op-chip" data-status={step.status}>{statusLabel(step.status)}</span>
                <span className="op-outcome__actions">
                  {step.node_refs.map((node) => (
                    <button key={`${node.run_id}:${node.node_id}`} type="button" className="op-link" title={node.run_id} onClick={() => onOpenRun(node.run_id)}>
                      Open result
                    </button>
                  ))}
                  {step.artifact_refs.map((artifact) => (
                    <span key={`${artifact.run_id}:${artifact.artifact_id}`}>
                      <button type="button" className="op-link" aria-expanded={shown?.key === `${artifact.run_id}:${artifact.artifact_id}`} onClick={() => void show(artifact.run_id, artifact.artifact_id)}>
                        View saved result
                      </button>
                      <a className="op-link" href={artifactUrl(projectRoot, artifact.run_id, artifact.artifact_id)} target="_blank" rel="noreferrer">
                        Download
                      </a>
                    </span>
                  ))}
                </span>
              </div>
              {step.error && <p role="alert">{step.error}</p>}
              {step.artifact_refs.map((artifact) => {
                const key = `${artifact.run_id}:${artifact.artifact_id}`;
                if (shown?.key !== key) return null;
                if (shown.error) return <p key={key} role="alert">{shown.error}</p>;
                if (shown.download) return <p key={key} className="op-note">This result is a file; use Download to open it.</p>;
                return <ResultValue key={key} value={shown.value} />;
              })}
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
