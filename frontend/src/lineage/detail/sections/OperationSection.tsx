// frontend/src/lineage/detail/sections/OperationSection.tsx
//
// v1.6.1 (2C.3) — editable operation panel.
//
// When a <RerunProvider> is in scope (the forest canvas supplies it), the model
// node's editable_schema is rendered as live controls (via the control_factory)
// with a submit that forks a new sibling run through POST /runs/{id}/rerun. The
// control initial values come from `editable_schema.value` (backfilled with the
// run's real current values by the backend, 2B.4). Submitting does NOT navigate;
// the provider refetches the head-set so the new branch grows in place.
//
// Without a provider (legacy DetailDrawer) the panel degrades to the read-only
// rows it shipped as in V1.5.2.

import { useMemo, useState } from "react";
import type { ReactNode } from "react";
import type {
  EditableControl,
  GraphViewNode,
} from "../../api/graphViewTypes";
import { renderControl, controlErrors } from "../../controls/controlFactory";
import { ResolverFailureState } from "../ResolverFailureState";
import { useResolvedNodeOperationContext } from "../NodeOperationContextProvider";
import { useRerun } from "../RerunContext";
import type { NodeOperationContextV1 } from "../../api/nodeOperationContext";
import {
  buildManualRerunPatch,
  buildManualRerunPatchId,
  type ManualRerunPatch,
} from "./manualRerunPatch";
import "./operationForms.css";

export function OperationSection({ node }: { node: GraphViewNode }) {
  const schema = node.editableSchema;
  const rerun = useRerun();
  const resolved = useResolvedNodeOperationContext();
  if (!schema || schema.length === 0) return null;
  // No rerun context → keep the V1.5.2 read-only rendering.
  if (!rerun) return <ReadOnlyOperation schema={schema} />;
  if (!resolved || !resolved.ok) {
    return (
      <ReadOnlyOperation schema={schema}>
        {resolved && !resolved.ok ? <ResolverFailureState result={resolved} /> : null}
      </ReadOnlyOperation>
    );
  }
  return (
    <EditableOperation
      key={`${resolved.context.context_fingerprint}:${resolved.context.selection.forest_node_key}`}
      node={node}
      schema={schema}
      context={resolved.context}
    />
  );
}

function EditableOperation({
  node,
  schema,
  context,
}: {
  node: GraphViewNode;
  schema: EditableControl[];
  context: NodeOperationContextV1;
}) {
  const rerun = useRerun()!;
  const initial = useMemo<Record<string, unknown>>(() => {
    const out: Record<string, unknown> = {};
    for (const control of schema) {
      if (control.value !== undefined) out[control.key] = control.value;
    }
    return out;
  }, [schema]);

  const [values, setValues] = useState<Record<string, unknown>>(initial);
  const [status, setStatus] = useState<"idle" | "submitting" | "done" | "error">(
    "idle",
  );
  const [error, setError] = useState<string | null>(null);
  const [previewPatch, setPreviewPatch] = useState<ManualRerunPatch | null>(null);

  const overrides = useMemo(() => {
    const diff: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(values)) {
      if (value !== initial[key]) diff[key] = value;
    }
    return diff;
  }, [values, initial]);

  const dirty = Object.keys(overrides).length > 0;
  const validationErrors = schema.flatMap(control => controlErrors({...control, value: values[control.key]}));

  const onChange = (key: string, value: unknown) => {
    setPreviewPatch(null);
    setValues((prev) => ({ ...prev, [key]: value }));
  };

  const onSubmit = async () => {
    if (validationErrors.length) return;
    if (!previewPatch) {
      const patch = buildManualRerunPatch({
        patchId: buildManualRerunPatchId(
          context.context_fingerprint,
          initial,
          values,
        ),
        sourceContextFingerprint: context.context_fingerprint,
        editableSchemaVersion: context.operation_target.editable_schema_source ?? "run_inputs",
        target: {
          owner_run_id: context.operation_target.owner_run_id,
          op_node_id: context.operation_target.op_node_id,
          node_hash: context.operation_target.node_hash,
        },
        initialValues: initial,
        currentValues: values,
      });
      setPreviewPatch(patch);
      return;
    }
    setStatus("submitting");
    setError(null);
    try {
      const response = await rerun.submitRerun({
        context,
        opOverrides: {},
        manualPatch: previewPatch,
      });
      setStatus("done");
      setPreviewPatch(null);
      if (response?.focus === null) {
        setError("Rerun completed, but focus target could not be resolved automatically.");
      }
    } catch (e) {
      setStatus("error");
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const row = (control: EditableControl) => (
    <div
      key={control.key}
      className="op-field"
      data-testid={`operation-control-${control.key}`}
      title={control.key === "x" ? "Uncheck a regressor to drop it. To add a column, go back to the analysis setup." : undefined}
    >
      <span className="op-field__label">{control.label}</span>
      {renderControl({ ...control, value: values[control.key] }, onChange)}
    </div>
  );
  const labelOf = (fieldId: string) => schema.find((control) => control.key === fieldId)?.label ?? fieldId;

  return (
    <section aria-label="Operation" data-testid="operation-section" className="op-panel">
      <div className="op-fields">{schema.filter((control) => !isAdvanced(control)).map(row)}</div>
      {schema.some(isAdvanced) && (
        <details className="op-advanced" open={schema.some(advancedInUse) || undefined}>
          <summary>Weights, survey design and other options</summary>
          <div className="op-fields">{schema.filter(isAdvanced).map(row)}</div>
        </details>
      )}
      {validationErrors.map(message => <p className="op-error" role="alert" key={message}>{message}</p>)}
      {previewPatch && (
        <ul className="op-preview" data-testid="manual-patch-preview">
          {previewPatch.changes.map((change) => (
            <li key={change.field_id}>
              <strong>{labelOf(change.field_id)}</strong> {changedValue(change.old_value)} → {changedValue(change.new_value)}
            </li>
          ))}
        </ul>
      )}
      <div className="op-actions">
        <button
          type="button"
          className="op-primary"
          data-testid="operation-rerun-submit"
          title="The current run stays as it is; this creates a new run beside it."
          disabled={!dirty || validationErrors.length > 0 || status === "submitting"}
          onClick={onSubmit}
        >
          {status === "submitting"
            ? "Rerunning..."
            : previewPatch
              ? "Run with these changes"
              : "Preview changes"}
        </button>
        {status === "done" && (
          <span data-testid="operation-rerun-done" className="op-success">{error ?? "Branch created"}</span>
        )}
        {status === "error" && (
          <span data-testid="operation-rerun-error" className="op-error">{error}</span>
        )}
      </div>
    </section>
  );
}

/** Survey design, weights and free-form settings: most reruns never touch them. */
function isAdvanced(control: EditableControl): boolean {
  return control.kind === "object" || control.kind === "json" || /weight|^survey_/.test(control.key);
}

/** A weight or design column already in use is part of this model: it must not sit folded away. */
function advancedInUse(control: EditableControl): boolean {
  const value = control.value;
  return isAdvanced(control) && !control.options && control.kind !== "object" && control.kind !== "json"
    && value !== null && value !== undefined && value !== "" && !(Array.isArray(value) && value.length === 0);
}

function changedValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "none";
  if (Array.isArray(value)) return value.join(", ") || "none";
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}

function ReadOnlyOperation({
  schema,
  children,
}: {
  schema: EditableControl[];
  children?: ReactNode;
}) {
  return (
    <section aria-label="Operation" data-testid="operation-section" style={{ marginTop: 18 }}>
      <div
        className="ln-section-label"
        style={{ marginBottom: 6, display: "flex", alignItems: "center" }}
      >
        <span>Operation</span>
        <span
          style={{
            marginLeft: "auto",
            fontSize: 11,
            color: "var(--label-tertiary)",
            fontStyle: "italic",
          }}
        >
          Read-only
        </span>
      </div>
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 4,
          padding: 10,
          background: "var(--bg-card-2)",
          borderRadius: 8,
          fontSize: 12,
        }}
      >
        {schema.map((control) => (
          <ReadOnlyControlRow key={control.key} control={control} />
        ))}
        {children}
      </div>
    </section>
  );
}

function ReadOnlyControlRow({ control }: { control: EditableControl }) {
  const value =
    typeof control.value === "object"
      ? JSON.stringify(control.value)
      : String(control.value ?? "—");
  return (
    <div
      data-testid={`operation-control-${control.key}`}
      style={{ display: "flex", gap: 8, alignItems: "baseline" }}
    >
      <span style={{ minWidth: 120, color: "var(--label-tertiary)", fontSize: 11 }}>
        {control.label}
      </span>
      <span
        style={{
          color: "var(--label)",
          fontFamily: "var(--font-mono, monospace)",
          fontSize: 12,
        }}
      >
        {value}
      </span>
    </div>
  );
}
