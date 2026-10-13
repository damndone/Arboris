// v1.9.0 — one step of a manual analysis: what it is, its parameters, and
// (after the first step) whether it reads an earlier step's output.

import { SchemaField } from "../SchemaFields";
import type { JsonSchema } from "../schemaModel";
import type { Operation, Target } from "../manualApi";
import { modelProducers, takesModel, withModelProducer, withSource, type Step } from "./steps";

export function StepCard({
  step,
  index,
  steps,
  operations,
  target,
  columns,
  onChange,
  onRemove,
}: {
  step: Step;
  index: number;
  steps: Step[];
  operations: Operation[];
  target?: Target;
  columns?: string[];
  onChange: (step: Step) => void;
  onRemove: () => void;
}) {
  const operation = operations.find((op) => op.id === step.operation_id);
  const name = (id: string) => operations.find((op) => op.id === id)?.name ?? "Earlier operation";
  const source = (step.spec.source as { from_step?: string } | undefined)?.from_step ?? "";
  const modelRef = String(step.spec.model_ref ?? "");
  const n = index + 1;

  return (
    <article className="op-step" aria-label={`Step ${n}: ${operation?.name ?? step.operation_id}`}>
      <header className="op-step__head">
        <span className="op-step__n" aria-hidden="true">{n}</span>
        <div className="op-step__what">
          <h3>{operation?.name ?? step.operation_id}</h3>
          {operation && <p>{operation.blurb ?? operation.summary}</p>}
        </div>
        <button type="button" className="ws-icon-button" aria-label={`Remove step ${n}`} title="Remove this step" onClick={onRemove}>
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" aria-hidden="true">
            <path d="M4 4l8 8M12 4l-8 8" />
          </svg>
        </button>
      </header>
      <div className="op-step__fields">
        <SchemaField
          key={step.step_id}
          label={`Step ${n}`}
          flat
          schema={(operation?.spec_schema ?? { type: "object" }) as JsonSchema}
          value={step.spec}
          onChange={(spec) => onChange({ ...step, spec: spec as Record<string, unknown> })}
          columns={columns}
        />
      </div>
      {index > 0 && (
        <details className="op-step__chain" open={!!source || modelRef.startsWith("step:")}>
          <summary>Use an earlier step's result</summary>
          <label className="manual-field">
            Dataset from
            <select aria-label={`Step ${n} dataset producer`} value={source} onChange={(event) => onChange(withSource(step, event.target.value))}>
              <option value="">The selected target</option>
              {steps.slice(0, index).map((earlier, position) => (
                <option key={earlier.step_id} value={earlier.step_id}>
                  {position + 1}. {name(earlier.operation_id)}
                </option>
              ))}
            </select>
          </label>
          {takesModel(operation) && (
            <label className="manual-field">
              Model from
              <select
                aria-label={`Step ${n} model producer`}
                value={modelRef.startsWith("step:") ? modelRef : ""}
                onChange={(event) => onChange(withModelProducer(step, event.target.value, target))}
              >
                <option value="">The selected model</option>
                {modelProducers(steps, index).map((option) => (
                  <option key={option.value} value={option.value}>{option.label}</option>
                ))}
              </select>
            </label>
          )}
        </details>
      )}
    </article>
  );
}
