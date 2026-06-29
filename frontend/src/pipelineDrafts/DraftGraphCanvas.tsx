import type { PipelineDraftV1 } from "../api";

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
  const edge = draft.graph.edges[0];

  return (
    <section aria-label="Draft graph" className="draft-graph">
      <button
        type="button"
        aria-pressed={selectedNodeId === input?.node_id}
        onClick={() => input && onSelectNode(input.node_id)}
      >
        <strong>Input Dataset</strong>
        <span>{input && "run_input_id" in input ? input.run_input_id : ""}</span>
      </button>
      <div aria-label="Draft edge">{edge ? `${edge.from} -> ${edge.to}` : "No edge"}</div>
      <button
        type="button"
        aria-pressed={selectedNodeId === model?.node_id}
        onClick={() => model && onSelectNode(model.node_id)}
      >
        <strong>Model</strong>
        <span>{model && "model_type" in model ? model.model_type : ""}</span>
      </button>
    </section>
  );
}
