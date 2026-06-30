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
}: {
  node: ModelNode;
  draftHash: string;
  onSave: (body: PipelineDraftPatchRequest) => void;
  onDirtyChange?: (dirty: boolean) => void;
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

  const controls = node.editable_schema as EditableControl[];
  const controlsWithValues = controls.map((control) => ({
    ...control,
    value: params[control.key] ?? control.value,
  }));

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
      <button type="button" onClick={() => setParams(node.source_params)}>
        Reset to source
      </button>
      <button
        type="button"
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
