// v1.9.0 — Analyze: every registered operation, run by hand without the
// Agent (the Agent calls the same catalog). The order on screen is the order
// of work: choose what to analyze, choose an operation, set its parameters,
// preview, confirm, read the results.
//
// A preview is bound to frozen tokens (request, preview, fingerprint); any
// edit discards it, so Confirm always runs exactly what was previewed. A
// failed request keeps its request id, so a retry is the same request.

import { useEffect, useRef, useState } from "react";
import { catalog, execute, type Operation, type Outcome, type Target } from "./manualApi";
import { OperationPicker } from "./operations/OperationPicker";
import { OutcomeView } from "./operations/OutcomeView";
import { StepCard } from "./operations/StepCard";
import { newStep, stepIssues, type Step } from "./operations/steps";
import { useTargetChoices, type ModelChoice } from "./operations/targets";
import "./manual.css";
import "./operations/operations.css";

export type { ModelChoice };

const uid = () => crypto.randomUUID();

export function OperationsPanel({
  projectRoot,
  runId,
  models,
  initialSearch = "",
  initialTarget,
  onClose,
  onRefresh,
  onOpenRun,
  onDedicated,
}: {
  projectRoot: string;
  runId: string;
  initialSearch?: string;
  initialTarget?: Target;
  models: ModelChoice[];
  onClose: () => void;
  onRefresh: () => void;
  onOpenRun: (runId: string) => void;
  onDedicated: (id: string, target?: Target) => void;
}) {
  // A run produced here can become the active run while Analyze is open; this
  // session stays bound to the run it was opened on.
  const [sourceRunId] = useState(runId);
  const [revision, setRevision] = useState(0);
  const { choices, error: targetError } = useTargetChoices(projectRoot, sourceRunId, models, revision);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [operations, setOperations] = useState<Operation[]>([]);
  const [catalogBusy, setCatalogBusy] = useState(true);
  const [steps, setSteps] = useState<Step[]>([]);
  const [picking, setPicking] = useState(false);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const requestId = useRef(uid());
  const pending = useRef(false);
  const form = useRef<HTMLFormElement>(null);

  const selectedIndex = choices?.findIndex((choice) => choice.key === selectedKey) ?? -1;
  const choice = selectedIndex >= 0 ? choices![selectedIndex] : undefined;
  const target = choice?.target;
  const targetKey = choice?.key ?? "";

  const invalidate = () => {
    setOutcome(null);
    setError("");
    requestId.current = uid();
  };

  // First load picks the requested target (or the first); a refresh that
  // drops the selected target discards the work built on it.
  useEffect(() => {
    if (!choices) return;
    if (selectedKey === null) {
      const wanted = initialTarget ? JSON.stringify(initialTarget) : undefined;
      setSelectedKey(choices.find((c) => c.key === wanted)?.key ?? choices[0]?.key ?? "");
    } else if (selectedKey && !choices.some((c) => c.key === selectedKey)) {
      invalidate();
      setSteps([]);
      setSelectedKey("");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [choices]);

  useEffect(() => {
    if (selectedKey === null) return;
    let live = true;
    setCatalogBusy(true);
    setOperations([]);
    catalog(projectRoot, target)
      .then((value) => live && setOperations(value.operations))
      .catch((reason) => live && setError(String(reason)))
      .finally(() => live && setCatalogBusy(false));
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectRoot, targetKey, selectedKey === null]);

  const chooseTarget = (key: string) => {
    invalidate();
    setSteps([]);
    setPicking(false);
    setSelectedKey(key);
  };
  const changeStep = (index: number, step: Step) => {
    invalidate();
    setSteps((old) => old.map((s, i) => (i === index ? step : s)));
  };
  const removeStep = (index: number) => {
    invalidate();
    setSteps((old) => old.filter((_, i) => i !== index));
  };
  const pick = (op: Operation) => {
    if (op.execution.kind !== "workflow") return onDedicated(op.id, target);
    invalidate();
    setSteps((old) => [...old, newStep(op, old.length, target, uid().slice(0, 4))]);
    setPicking(false);
  };

  async function submit(confirm = false) {
    if (pending.current || !form.current?.reportValidity()) return;
    const issues = stepIssues(steps, operations);
    if (issues.length) return setError(issues.join("\n"));
    if (!target && !confirm) return;
    pending.current = true;
    setBusy(true);
    setError("");
    try {
      const body =
        confirm && outcome
          ? { mode: "confirm" as const, request_id: outcome.request_id, preview_id: outcome.preview_id, fingerprint: outcome.fingerprint }
          : { mode: "preview" as const, request_id: requestId.current, target, steps };
      const result = await execute(projectRoot, body);
      setOutcome(result);
      if (["completed", "partial", "failed"].includes(result.status)) {
        setRevision((n) => n + 1);
        onRefresh();
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      pending.current = false;
      setBusy(false);
    }
  }

  const showPicker = steps.length === 0 || picking;
  const groups = (["Data", "Model"] as const).map((kind) => ({
    kind,
    items: (choices ?? []).map((c, index) => ({ c, index })).filter(({ c }) => c.kind === kind),
  }));

  return (
    <section className="manual-panel op-panel" aria-label="Analyze operations">
      <header className="op-head">
        <h2>Analyze</h2>
        <label className="op-target">
          <span>On</span>
          <select
            aria-label="Analysis target"
            disabled={busy}
            value={selectedIndex >= 0 ? String(selectedIndex) : ""}
            onChange={(event) => chooseTarget(choices?.[Number(event.target.value)]?.key ?? "")}
          >
            <option value="">Nothing selected</option>
            {groups.map(({ kind, items }) =>
              items.length ? (
                <optgroup key={kind} label={kind === "Data" ? "Data" : "Models"}>
                  {items.map(({ c, index }) => (
                    <option key={c.key} value={index}>{c.label}</option>
                  ))}
                </optgroup>
              ) : null,
            )}
          </select>
        </label>
        {target && (
          <details className="op-source">
            <summary>Source details</summary>
            <dl>
              {Object.entries(target).map(([key, value]) => (
                <div key={key}>
                  <dt>{key.replace(/_/g, " ")}</dt>
                  <dd>{String(value)}</dd>
                </div>
              ))}
            </dl>
          </details>
        )}
        <button type="button" className="ws-icon-button op-close" aria-label="Close Analyze" title="Close" onClick={onClose} disabled={busy}>
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" aria-hidden="true">
            <path d="M4 4l8 8M12 4l-8 8" />
          </svg>
        </button>
      </header>
      <p className="op-lede">Runs on this machine, without a language model. The Agent uses the same operations.</p>

      {(error || targetError) && <p role="alert">{error || targetError}</p>}
      {choices?.length === 0 && <p className="op-note">Import data with New analysis first.</p>}

      {steps.length > 0 && (
        <form
          ref={form}
          className="op-steps"
          onChange={invalidate}
          onSubmit={(event) => {
            event.preventDefault();
            void submit();
          }}
        >
          <fieldset disabled={busy}>
            <legend className="ws-visually-hidden">Steps</legend>
            {steps.map((step, index) => (
              <StepCard
                key={step.step_id}
                step={step}
                index={index}
                steps={steps}
                operations={operations}
                target={target}
                columns={choice?.columns}
                onChange={(next) => changeStep(index, next)}
                onRemove={() => removeStep(index)}
              />
            ))}
            <div className="op-bar">
              <button type="button" className="op-secondary" aria-expanded={picking} onClick={() => setPicking(!picking)}>
                {picking ? "Done adding" : "Add a step"}
              </button>
              <span className="op-bar__spacer" />
              <button type="submit" className="op-primary" disabled={!target || catalogBusy || busy}>
                Preview analysis
              </button>
            </div>
          </fieldset>
        </form>
      )}

      {outcome && (
        <OutcomeView projectRoot={projectRoot} outcome={outcome} operations={operations} busy={busy} onConfirm={() => void submit(true)} onOpenRun={onOpenRun} />
      )}
      {busy && <p className="op-note" role="status">Working…</p>}

      {showPicker &&
        (catalogBusy ? (
          <p className="op-note" role="status">Loading operations…</p>
        ) : (
          <OperationPicker key={initialSearch} operations={operations} target={target} busy={busy} initialSearch={initialSearch} onPick={pick} />
        ))}
    </section>
  );
}
