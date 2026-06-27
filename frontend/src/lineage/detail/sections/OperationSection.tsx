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
import { renderControl } from "../../controls/controlFactory";
import { ResolverFailureState } from "../ResolverFailureState";
import { useResolvedNodeOperationContext } from "../NodeOperationContextProvider";
import { useRerun } from "../RerunContext";
import type { NodeOperationContextV1 } from "../../api/nodeOperationContext";

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
      schema={schema}
      context={resolved.context}
    />
  );
}

function EditableOperation({
  schema,
  context,
}: {
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

  const overrides = useMemo(() => {
    const diff: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(values)) {
      if (value !== initial[key]) diff[key] = value;
    }
    return diff;
  }, [values, initial]);

  const dirty = Object.keys(overrides).length > 0;

  const onChange = (key: string, value: unknown) =>
    setValues((prev) => ({ ...prev, [key]: value }));

  const onSubmit = async () => {
    setStatus("submitting");
    setError(null);
    try {
      const response = await rerun.submitRerun({ context, opOverrides: overrides });
      setStatus("done");
      if (response?.focus === null) {
        setError("Rerun completed, but focus target could not be resolved automatically.");
      }
    } catch (e) {
      setStatus("error");
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <section aria-label="Operation" data-testid="operation-section" style={{ marginTop: 18 }}>
      <div className="ln-section-label" style={{ marginBottom: 6 }}>
        Operation
      </div>
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 8,
          padding: 10,
          background: "var(--bg-card-2, rgba(255,255,255,0.04))",
          borderRadius: 8,
          fontSize: 12,
        }}
      >
        {schema.map((control) => (
          <label
            key={control.key}
            data-testid={`operation-control-${control.key}`}
            style={{ display: "flex", gap: 8, alignItems: "center" }}
          >
            <span style={{ minWidth: 120, color: "var(--label-tertiary)", fontSize: 11 }}>
              {control.label}
            </span>
            {renderControl({ ...control, value: values[control.key] }, onChange)}
          </label>
        ))}
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 4 }}>
          <button
            type="button"
            data-testid="operation-rerun-submit"
            disabled={!dirty || status === "submitting"}
            onClick={onSubmit}
          >
            {status === "submitting" ? "Rerunning…" : "Rerun from here"}
          </button>
          {status === "done" && (
            <span data-testid="operation-rerun-done" style={{ color: "var(--accent-positive, #4caf50)" }}>
              {error ?? "Branch created"}
            </span>
          )}
          {status === "error" && (
            <span data-testid="operation-rerun-error" style={{ color: "var(--accent-negative, #e57373)" }}>
              {error}
            </span>
          )}
        </div>
      </div>
    </section>
  );
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
          background: "var(--bg-card-2, rgba(255,255,255,0.04))",
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
        {control.unit ? ` ${control.unit}` : ""}
      </span>
    </div>
  );
}
