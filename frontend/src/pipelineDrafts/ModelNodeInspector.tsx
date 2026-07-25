import { useEffect, useMemo, useState } from "react";
import type { PipelineDraftNode, PipelineDraftPatchRequest } from "../api";
import type { EditableControl } from "../lineage/api/graphViewTypes";
import { renderControl } from "../lineage/controls/controlFactory";

type ModelNode = Extract<PipelineDraftNode, { node_type: "model" }>;

function stableParams(value: Record<string, unknown>): string {
  const normalize = (item: unknown): unknown => {
    if (Array.isArray(item)) return item.map(normalize);
    if (item && typeof item === "object") {
      return Object.fromEntries(
        Object.entries(item as Record<string, unknown>)
          .sort(([a], [b]) => a.localeCompare(b))
          .map(([key, nested]) => [key, normalize(nested)]),
      );
    }
    return item;
  };
  return JSON.stringify(normalize(value));
}

export function ModelNodeInspector({
  node,
  draftHash,
  onSave,
  onDirtyChange,
  disabled = false,
}: {
  node: ModelNode;
  draftHash: string;
  onSave: (body: PipelineDraftPatchRequest) => void;
  onDirtyChange?: (dirty: boolean) => void;
  disabled?: boolean;
}) {
  const [params, setParams] = useState<Record<string, unknown>>(node.params);
  const baseParamsKey = useMemo(() => stableParams(node.params), [node.params]);
  const paramsKey = useMemo(() => stableParams(params), [params]);
  const dirty = paramsKey !== baseParamsKey;

  useEffect(() => {
    setParams(node.params);
  }, [node]);

  useEffect(() => {
    onDirtyChange?.(dirty);
  }, [dirty, onDirtyChange]);

  // OLS keeps its human-facing covariance select as the editable control.
  // The object-shaped Agent envelope is still present in the backend schema
  // for typed Notebook reruns, but rendering it here would expose a duplicate
  // opaque JSON field beside the real covariance control.
  const controls = ((node.editable_schema ?? []) as EditableControl[]).filter(
    (control) => !(control.key === "model_options" && String(control.kind) === "object"),
  );
  const controlsWithValues = controls.map((control) => ({
    ...control,
    value: params[control.key] ?? control.value,
  }));

  // v1.6.5 (§6.5): changed-fields summary — which params differ from the
  // source model, shown as `key: source → current` so the user sees exactly
  // what this draft edits before validating/executing.
  const fmt = (v: unknown): string =>
    v === undefined || v === "" ? "∅" : Array.isArray(v) ? `[${v.join(", ")}]` : String(v);
  const changedFields = Array.from(
    new Set([...Object.keys(node.source_params ?? {}), ...Object.keys(params)]),
  )
    .filter((key) => stableParams({ v: params[key] }) !== stableParams({ v: node.source_params?.[key] }))
    .sort();

  return (
    <section aria-label="Model node inspector">
      <h2>ModelNode</h2>
      <dl>
        <dt>Model type</dt>
        <dd>{node.model_type}</dd>
        <dt>Schema</dt>
        <dd>{node.schema_id}</dd>
      </dl>
      {controlsWithValues.map((control) => (
        <div key={control.key}>{renderControl(control, (key, value) => {
          setParams((prev) => ({ ...prev, [key]: value }));
        })}</div>
      ))}
      <section aria-label="Changed fields" data-testid="changed-fields-summary">
        <h3>Changed fields</h3>
        {changedFields.length === 0 ? (
          <p>No changes from source</p>
        ) : (
          <ul>
            {changedFields.map((key) => (
              <li key={key}>
                {key}: {fmt(node.source_params?.[key])} → {fmt(params[key])}
              </li>
            ))}
          </ul>
        )}
      </section>
      <button type="button" onClick={() => setParams(node.source_params ?? {})}>
        Reset to source
      </button>
      <button
        type="button"
        disabled={disabled}
        onClick={() => {
          onSave({
            model_node_id: node.node_id,
            base_draft_hash: draftHash,
            params,
          });
        }}
      >
        Save changes
      </button>
    </section>
  );
}
