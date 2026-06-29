import { useState } from "react";
import type { PipelineDraftNode, PipelineDraftPatchRequest } from "../api";
import type { EditableControl } from "../lineage/api/graphViewTypes";
import { renderControl } from "../lineage/controls/controlFactory";

type ModelNode = Extract<PipelineDraftNode, { node_type: "model" }>;

export function ModelNodeInspector({
  node,
  draftHash,
  onSave,
}: {
  node: ModelNode;
  draftHash: string;
  onSave: (body: PipelineDraftPatchRequest) => void;
}) {
  const [params, setParams] = useState<Record<string, unknown>>(node.params);
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
