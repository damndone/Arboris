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
  const options = step.spec.options as Record<string, unknown> | undefined;
  const savedIndex = operation?.saved_models?.findIndex((model) => model.run_id === options?.model_run_id
    && model.artifact_id === options?.model_artifact_id && model.sha256 === options?.model_sha256) ?? -1;
  const classification = operation?.saved_models?.[savedIndex]?.model_type === "native_random_forest_classification";

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
        {step.operation_id === "prediction.native_forest_apply" ? <>
          <label className="manual-field">
            Saved model
            <select aria-label="Saved model" required value={savedIndex < 0 ? "" : String(savedIndex)}
              onChange={(event) => {
                const model = operation!.saved_models![Number(event.target.value)];
                const { probability_column, ...regressionOptions } = options ?? {};
                onChange({ ...step, spec: { ...step.spec, options: { ...regressionOptions,
                  ...(model.model_type === "native_random_forest_classification" ? { probability_column: probability_column ?? "probability" } : {}),
                  model_run_id: model.run_id, model_artifact_id: model.artifact_id, model_sha256: model.sha256,
                } } });
              }}>
              <option value="" disabled>Choose a saved forest…</option>
              {operation?.saved_models?.map((model, index) => <option key={`${model.run_id}:${model.artifact_id}`} value={index}>
                {model.model_type === "native_random_forest_classification" ? "Binary classification" : "Regression"} · {model.label}
              </option>)}
            </select>
          </label>
          {!operation?.saved_models?.length && <p>No compatible saved forests are available in this project.</p>}
          {savedIndex < 0 && Boolean(options?.model_run_id) && <p role="alert">The previously selected model is no longer available. Choose a saved model before previewing.</p>}
          {savedIndex >= 0 && <p>Required columns: {operation!.saved_models![savedIndex].predictors.join(", ")}</p>}
          <SchemaField label={`Step ${n}.options.prediction_column`} required
            schema={(operation?.spec_schema as JsonSchema)?.properties?.options.properties?.prediction_column ?? { type: "string" }}
            value={options?.prediction_column}
            onChange={(prediction_column) => onChange({ ...step, spec: { ...step.spec, options: { ...options, prediction_column } } })} />
          {classification && <>
            <SchemaField label={`Step ${n}.options.probability_column`} required
              schema={(operation?.spec_schema as JsonSchema)?.properties?.options.properties?.probability_column ?? { type: "string" }}
              value={options?.probability_column ?? "probability"}
              onChange={(probability_column) => onChange({ ...step, spec: { ...step.spec, options: { ...options, probability_column } } })} />
            <p>The prediction column contains class 1 when its probability is at least 0.5, otherwise class 0. These are predictions, not measured accuracy on the new data.</p>
          </>}
        </> : <SchemaField
          key={step.step_id}
          label={`Step ${n}`}
          flat
          schema={(operation?.spec_schema ?? { type: "object" }) as JsonSchema}
          value={step.spec}
          onChange={(spec) => onChange({ ...step, spec: spec as Record<string, unknown> })}
          columns={columns}
        />}
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
