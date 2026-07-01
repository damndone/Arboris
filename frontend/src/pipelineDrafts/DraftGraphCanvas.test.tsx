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

test("renders fixed InputNode → ModelNode as node cards with a connector", () => {
  render(
    <DraftGraphCanvas
      draft={draft}
      selectedNodeId="input_1"
      onSelectNode={() => {}}
    />,
  );

  expect(screen.getByText("Input Dataset")).toBeInTheDocument();
  expect(screen.getByText("Model")).toBeInTheDocument();
  // model card surfaces the model_type + schema id
  expect(screen.getByText("ols")).toBeInTheDocument();
  // a visual connector between the two cards (replaces the raw "a -> b" text)
  expect(screen.getByTestId("draft-edge")).toBeInTheDocument();
  // selected input card reflects selection
  const inputCard = screen.getByRole("button", { name: /Input Dataset/i });
  expect(inputCard).toHaveAttribute("aria-pressed", "true");
});
