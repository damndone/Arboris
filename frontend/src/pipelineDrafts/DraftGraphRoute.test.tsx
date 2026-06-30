import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useNavigate } from "react-router-dom";
import { vi } from "vitest";
import * as api from "../api";
import { DraftGraphRoute } from "./DraftGraphRoute";

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
  return { ...actual, useNavigate: vi.fn() };
});

vi.mock("../api");

function makeDraftResponse({
  draftHash = "h1",
  covariance = "",
  editable = false,
}: {
  draftHash?: string;
  covariance?: string;
  editable?: boolean;
} = {}) {
  return {
    draft_hash: draftHash,
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
            editable_schema: editable
              ? [
                  {
                    kind: "select",
                    key: "covariance",
                    label: "Covariance",
                    value: covariance,
                    options: ["", "robust", "clustered"],
                  },
                ]
              : [],
            editable_schema_hash: "schema",
            source_ref: {},
            source_params: editable ? { covariance: "" } : {},
            params: editable ? { covariance } : {},
          },
        ],
        edges: [{ from: "input_1", to: "model_1" }],
      },
      default_execution_mode: "rerun_child",
    },
  } satisfies api.PipelineDraftResponse;
}

test("loads draft and keeps execute disabled until validated current hash", async () => {
  vi.mocked(useNavigate).mockReturnValue(vi.fn());
  vi.mocked(api.getPipelineDraft).mockResolvedValue(makeDraftResponse());
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

test("execute pending_index navigates to lineage without requiring target node id", async () => {
  const navigate = vi.fn();
  vi.mocked(useNavigate).mockReturnValue(navigate);
  vi.mocked(api.getPipelineDraft).mockResolvedValue(makeDraftResponse({ draftHash: "h1" }));
  vi.mocked(api.validatePipelineDraft).mockResolvedValue({
    ok: true,
    status: "valid",
    executable: true,
    checks: [],
    resolved_execution: {
      execution_mode: "rerun_child",
      compare_source_available: true,
      rerun_from_run_id: "run_parent",
      rerun_from_model_node_id: "model_parent",
      rerun_from_op_node_id: "op_parent",
    },
    validated_draft_hash: "h1",
    validated_execution_mode: "rerun_child",
    validated_at: "2026-06-29T00:00:00Z",
  });
  vi.mocked(api.executePipelineDraft).mockResolvedValue({
    ok: true,
    run_id: "run_child",
    draft_id: "draft_1",
    executed_draft_hash: "h1",
    execution_mode: "rerun_child",
    produced_lineage: {
      rerun_from_run_id: "run_parent",
      rerun_from_model_node_id: "model_parent",
      rerun_from_op_node_id: "op_parent",
    },
    focus: {
      status: "pending_index",
      run_id: "run_child",
      poll: {
        rerun_from_run_id: "run_parent",
        rerun_from_model_node_id: "model_parent",
        rerun_from_op_node_id: "op_parent",
      },
    },
  });
  render(
    <MemoryRouter initialEntries={["/pipeline-drafts/draft_1?project_root=/tmp/project"]}>
      <Routes>
        <Route path="/pipeline-drafts/:draftId" element={<DraftGraphRoute />} />
      </Routes>
    </MemoryRouter>,
  );

  await screen.findByText("Input Dataset");
  fireEvent.click(screen.getByRole("button", { name: "Validate" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Execute Draft" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "Execute Draft" }));

  await waitFor(() =>
    expect(navigate).toHaveBeenCalledWith(
      "/runs/run_child?project_root=%2Ftmp%2Fproject&tab=lineage&pending_source_run_id=run_parent&pending_source_model_node_id=model_parent&pending_source_op_node_id=op_parent",
    ),
  );
});

test("disables validate and execute while model edits are unsaved", async () => {
  vi.mocked(useNavigate).mockReturnValue(vi.fn());
  vi.mocked(api.getPipelineDraft).mockResolvedValue(
    makeDraftResponse({ draftHash: "h1", editable: true }),
  );
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

  await screen.findByText("Input Dataset");
  fireEvent.click(screen.getByRole("button", { name: /Model ols/ }));
  fireEvent.change(screen.getByLabelText("Covariance"), { target: { value: "robust" } });

  expect(screen.getByText("Unsaved")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Validate" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Execute Draft" })).toBeDisabled();
});

test("reloads draft and marks validation stale after draft hash conflict", async () => {
  vi.mocked(useNavigate).mockReturnValue(vi.fn());
  const latest = makeDraftResponse({ draftHash: "h2", covariance: "clustered", editable: true });
  vi.mocked(api.getPipelineDraft)
    .mockResolvedValueOnce(makeDraftResponse({ draftHash: "h1", editable: true }))
    .mockResolvedValue(latest);
  vi.mocked(api.patchPipelineDraftParams).mockRejectedValue({ status: 409 });

  render(
    <MemoryRouter initialEntries={["/pipeline-drafts/draft_1?project_root=/tmp/project"]}>
      <Routes>
        <Route path="/pipeline-drafts/:draftId" element={<DraftGraphRoute />} />
      </Routes>
    </MemoryRouter>,
  );

  await screen.findByText("Input Dataset");
  fireEvent.click(screen.getByRole("button", { name: /Model ols/ }));
  fireEvent.change(screen.getByLabelText("Covariance"), { target: { value: "robust" } });
  fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

  await waitFor(() => expect(screen.getByText("Validation stale")).toBeInTheDocument());
  expect(api.getPipelineDraft).toHaveBeenCalledWith("/tmp/project", "draft_1");
  expect(vi.mocked(api.getPipelineDraft).mock.calls.length).toBeGreaterThanOrEqual(2);
  expect(api.getPipelineDraft).toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "Execute Draft" })).toBeDisabled();
});
