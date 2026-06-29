import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { vi } from "vitest";
import * as api from "../api";
import { DraftGraphRoute } from "./DraftGraphRoute";

vi.mock("../api");

test("loads draft and keeps execute disabled until validated current hash", async () => {
  vi.mocked(api.getPipelineDraft).mockResolvedValue({
    draft_hash: "h1",
    draft: {
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
            editable_schema_hash: "schema",
            source_ref: {},
            source_params: {},
            params: {},
          },
        ],
        edges: [{ from: "input_1", to: "model_1" }],
      },
      default_execution_mode: "rerun_child",
    },
  });
  vi.mocked(api.validatePipelineDraft).mockResolvedValue({
    ok: true,
    status: "valid",
    executable: true,
    checks: [],
    resolved_execution: {
      execution_mode: "rerun_child",
      compare_source_available: true,
    },
    validated_execution_mode: "rerun_child",
    validated_draft_hash: "h1",
    validated_at: "",
  });

  render(
    <MemoryRouter initialEntries={["/pipeline-drafts/draft_1?project_root=/tmp/project"]}>
      <Routes>
        <Route path="/pipeline-drafts/:draftId" element={<DraftGraphRoute />} />
      </Routes>
    </MemoryRouter>,
  );

  expect(await screen.findByText("Input Dataset")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Execute Draft" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Validate" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Execute Draft" })).toBeEnabled());
});
