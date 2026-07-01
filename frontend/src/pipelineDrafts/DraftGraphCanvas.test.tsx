import { render, screen } from "@testing-library/react";
import { DraftGraphCanvas } from "./DraftGraphCanvas";
import type { PipelineDraftV1 } from "../api";

const draft: PipelineDraftV1 = {
  draft_id: "draft_1",
  schema_version: "pipeline_draft.v1",
  created_at: "",
  updated_at: "",
  status: "draft",
  graph: {
    nodes: [
      {
        node_id: "input_1",
        node_type: "input.dataset",
        source_type: "run_input",
        run_input_id: "run_1",
        input_fingerprint: "i",
        schema_fingerprint: "s",
        status: "bound",
      },
      {
        node_id: "model_1",
        node_type: "model",
        model_family: "regression",
        model_type: "ols",
        schema_id: "ols@v1",
        editable_schema: [],
        editable_schema_hash: "h",
        source_ref: {},
        source_params: {},
        params: {},
      },
    ],
    edges: [{ from: "input_1", to: "model_1" }],
  },
  default_execution_mode: "rerun_child",
};

test("renders fixed InputNode to ModelNode graph", () => {
  render(
    <DraftGraphCanvas
      draft={draft}
      selectedNodeId="input_1"
      onSelectNode={() => {}}
    />,
  );

  expect(screen.getByText("Input Dataset")).toBeInTheDocument();
  expect(screen.getByText("Model")).toBeInTheDocument();
  expect(screen.getByText("input_1 -> model_1")).toBeInTheDocument();
});
