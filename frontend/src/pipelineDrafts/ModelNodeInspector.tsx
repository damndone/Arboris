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
  const fmt = (v: unknown): string => {
    if (v === undefined || v === "") return "∅";
    if (Array.isArray(v)) return `${v.length} ${v.length === 1 ? "item" : "items"}`;
    if (v && typeof v === "object") {
      const count = Object.keys(v as Record<string, unknown>).length;
      return `${count} ${count === 1 ? "setting" : "settings"}`;
    }
    return String(v);
  };
  const exact = (v: unknown): string => {
    if (v === undefined || v === "") return "∅";
    if (typeof v === "string") return v;
    return JSON.stringify(v);
  };
  const changedFields = Array.from(
    new Set([...Object.keys(node.source_params ?? {}), ...Object.keys(params)]),
  )
    .filter((key) => stableParams({ v: params[key] }) !== stableParams({ v: node.source_params?.[key] }))
    .sort();

  return (
    <section className="model-node-inspector" aria-label="Model node inspector">
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
      <details
        className="model-node-inspector__changes"
        aria-label="Changed fields"
        data-testid="changed-fields-summary"
      >
        <summary>
          <span>Changed fields</span>
          <span className="model-node-inspector__change-count">
            {`${changedFields.length} ${
              changedFields.length === 1 ? "change" : "changes"
            }`}
          </span>
        </summary>
        {changedFields.length === 0 ? (
          <p>No changes from source</p>
        ) : (
          <ul>
            {changedFields.map((key) => (
              <li key={key}>
                <code>{key}</code>
                <span className="model-node-inspector__change-values">
                  <span title={exact(node.source_params?.[key])}>
                    {fmt(node.source_params?.[key])}
                  </span>
                  <span aria-hidden="true">→</span>
                  <span
                    data-testid={`changed-field-value-${key}`}
                    title={exact(params[key])}
                  >
                    {fmt(params[key])}
                  </span>
                </span>
              </li>
            ))}
          </ul>
        )}
      </details>
      <div className="model-node-inspector__actions" data-testid="model-editor-actions">
        <button
          type="button"
          className="draft-button draft-button--secondary"
          onClick={() => setParams(node.source_params ?? {})}
        >
          Reset to source
        </button>
        <button
          type="button"
          className="draft-button draft-button--primary"
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
      </div>
    </section>
  );
}
