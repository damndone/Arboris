// Bespoke ARMA-GARCH node operation form for the lineage drawer.
//
// The generic OperationSection renders editable_schema controls; for the
// time-series pack that is an opaque `model_options` object. This section
// instead reuses the run-form's ArmaGarchControls (and its build/parse/validate
// helpers) so a user edits transform / orders / distribution / strategy /
// validation as real controls, then forks a child model via the existing rerun
// path (op override `model_options`, canonicalized server-side).

import { useMemo, useState } from "react";
import type { GraphViewNode } from "../../api/graphViewTypes";
import { useRerun } from "../RerunContext";
import { useResolvedNodeOperationContext } from "../NodeOperationContextProvider";
import {
  ArmaGarchControls,
  armaGarchValidationErrors,
  armaGarchValueFromModelOptions,
  buildArmaGarchModelOptions,
  createDefaultArmaGarchValue,
  type ArmaGarchControlValue,
} from "../../../runForm/ArmaGarchControls";

function currentModelOptions(node: GraphViewNode): Record<string, unknown> {
  const schema = ("editableSchema" in node ? node.editableSchema : undefined) ?? [];
  const control = schema.find((entry) => entry.key === "model_options");
  const value = control?.value;
  return value && typeof value === "object" ? (value as Record<string, unknown>) : {};
}

export function ArmaGarchOperationSection({ node }: { node: GraphViewNode }) {
  const rerun = useRerun();
  const resolved = useResolvedNodeOperationContext();

  const options = useMemo(() => currentModelOptions(node), [node]);
  const initial = useMemo(
    () => armaGarchValueFromModelOptions(options, createDefaultArmaGarchValue()),
    [options],
  );
  const [value, setValue] = useState<ArmaGarchControlValue>(initial);
  const [status, setStatus] = useState<"idle" | "submitting" | "done" | "error">("idle");
  const [error, setError] = useState<string | null>(null);

  const datasetRef = String(options.dataset_ref ?? "");
  const columns = useMemo(
    () => [initial.timeColumn, initial.valueColumn].filter((c): c is string => Boolean(c)),
    [initial],
  );
  const errors = armaGarchValidationErrors(value);
  const dirty = JSON.stringify(value) !== JSON.stringify(initial);

  if (!rerun || !resolved || !resolved.ok) return null;

  const onSubmit = async () => {
    setStatus("submitting");
    setError(null);
    try {
      await rerun.submitRerun({
        context: resolved.context,
        opOverrides: { model_options: buildArmaGarchModelOptions(value, datasetRef) },
      });
      setStatus("done");
    } catch (e) {
      setStatus("error");
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <section
      aria-label="ARMA-GARCH operation"
      data-testid="arma-garch-operation-section"
      style={{ marginTop: 18 }}
    >
      <div className="ln-section-label" style={{ marginBottom: 6 }}>
        Operation
      </div>
      <div
        data-testid="arma-garch-op-explanation"
        style={{ color: "var(--label-tertiary)", fontSize: 11, marginBottom: 8 }}
      >
        The current run stays unchanged. Confirming forks a new child model.
      </div>
      <ArmaGarchControls columns={columns} preview={null} value={value} onChange={setValue} />
      {errors.length > 0 && (
        <ul data-testid="arma-garch-op-errors" style={{ color: "var(--accent-negative, #e57373)", fontSize: 11 }}>
          {errors.map((message) => (
            <li key={message}>{message}</li>
          ))}
        </ul>
      )}
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 8 }}>
        <button
          type="button"
          data-testid="arma-garch-op-submit"
          disabled={!dirty || errors.length > 0 || status === "submitting"}
          onClick={onSubmit}
        >
          {status === "submitting" ? "Forking child…" : "Rerun as new child model"}
        </button>
        {status === "done" && (
          <span data-testid="arma-garch-op-done" style={{ color: "var(--accent-positive, #4caf50)" }}>
            Branch created
          </span>
        )}
        {status === "error" && (
          <span data-testid="arma-garch-op-error" style={{ color: "var(--accent-negative, #e57373)" }}>
            {error}
          </span>
        )}
      </div>
    </section>
  );
}
