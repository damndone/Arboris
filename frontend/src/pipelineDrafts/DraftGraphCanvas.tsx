import type { PipelineDraftV1 } from "../api";

// v1.6.5 (P7): the fixed InputNode → ModelNode draft graph, rendered as two
// proper node cards joined by a visual connector (was a bare button stack +
// "a -> b" text). Still a FIXED two-node graph per v1.6.4 spec §6.3 — not a
// DAG builder. Clicking a card selects it for the inspector.

export function DraftGraphCanvas({
  draft,
  selectedNodeId,
  onSelectNode,
}: {
  draft: PipelineDraftV1;
  selectedNodeId: string | null;
  onSelectNode: (nodeId: string) => void;
}) {
  const input = draft.graph.nodes.find((node) => node.node_type === "input.dataset");
  const model = draft.graph.nodes.find((node) => node.node_type === "model");

  return (
    <div className="draft-graph" data-testid="draft-canvas">
      {input && (
        <button
          type="button"
          className={`draft-node draft-node--input${
            selectedNodeId === input.node_id ? " draft-node--selected" : ""
          }`}
          aria-pressed={selectedNodeId === input.node_id}
          onClick={() => onSelectNode(input.node_id)}
        >
          <span className="draft-node__kind">Input Dataset</span>
          <span className="draft-node__title">
            {"run_input_id" in input ? input.run_input_id : ""}
          </span>
          <span className="draft-node__meta">bound to source run</span>
        </button>
      )}

      <div className="draft-edge" data-testid="draft-edge" aria-hidden>
        →
      </div>

      {model && (
        <button
          type="button"
          className={`draft-node draft-node--model${
            selectedNodeId === model.node_id ? " draft-node--selected" : ""
          }`}
          aria-pressed={selectedNodeId === model.node_id}
          onClick={() => onSelectNode(model.node_id)}
        >
          <span className="draft-node__kind">Model</span>
          <span className="draft-node__title">
            {"model_type" in model ? model.model_type : ""}
          </span>
          <span className="draft-node__meta">
            {"schema_id" in model ? model.schema_id : ""}
          </span>
        </button>
      )}
    </div>
  );
}
