import * as React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useNavigate } from "react-router-dom";
import { vi } from "vitest";
import * as api from "../api";
import * as notebookApi from "../notebook/notebookApi";
import { DraftGraphRoute } from "./DraftGraphRoute";

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
  const future = { v7_startTransition: true, v7_relativeSplatPath: true };
  return {
    ...actual,
    MemoryRouter: (props: React.ComponentProps<typeof actual.MemoryRouter>) =>
      React.createElement(actual.MemoryRouter, {
        ...props,
        future: { ...future, ...props.future },
      }),
    useNavigate: vi.fn(),
  };
});

vi.mock("../api");
vi.mock("../notebook/notebookApi");

function makeDraftResponse({
  draftHash = "h1",
  covariance = "",
  editable = false,
  executionMode = "rerun_child",
}: {
  draftHash?: string;
  covariance?: string;
  editable?: boolean;
  executionMode?: api.DraftExecutionMode;
} = {}) {
  return {
    draft_hash: draftHash,
    draft: {
      draft_id: "draft_1",
      schema_version: "pipeline_draft.v1",
      created_at: "",
      updated_at: "",
      status: "draft",
      created_from: {
        source_type: "run",
        source_run_id: "run_parent",
        source_model_node_id: "model_parent",
      },
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
      default_execution_mode: executionMode,
    },
  } satisfies api.PipelineDraftResponse;
}

function makeGenesisDraftResponse() {
  return {
    draft_hash: "g1",
    draft: {
      draft_id: "draft_genesis",
      schema_version: "pipeline_draft.v1",
      created_at: "",
      updated_at: "",
      status: "draft",
      created_from: {
        source_type: "genesis",
        source_input_fingerprint: "upload_sha",
      },
      notebook_provenance: {
        notebook_id: "nb_1",
        option_id: "opt_1",
        option_revision: "1",
      },
      graph: {
        nodes: [
          {
            node_id: "source_1",
            node_type: "input.upload",
            upload: { sha256: "upload_sha", filename: "data.csv" },
            sheet_names: [],
            status: "bound",
          },
          {
            node_id: "table_1",
            node_type: "table",
            columns: ["outcome", "treatment"],
            params: { sheet_name: null, transpose: false },
            status: "configured",
          },
          {
            node_id: "model_1",
            node_type: "model",
            model_family: "regression",
            model_type: "ols",
            params: { model_type: "ols", y: "outcome", x: ["treatment"] },
            status: "configured",
          },
        ],
        edges: [
          { from: "source_1", to: "table_1" },
          { from: "table_1", to: "model_1" },
        ],
      },
      default_execution_mode: "genesis",
    },
  } as unknown as api.PipelineDraftResponse;
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

test("shows an error when draft loading fails", async () => {
  vi.mocked(useNavigate).mockReturnValue(vi.fn());
  vi.mocked(api.getPipelineDraft).mockRejectedValue(
    Object.assign(new Error("DRAFT_NOT_FOUND"), { status: 404 }),
  );

  render(
    <MemoryRouter initialEntries={["/pipeline-drafts/draft_1?project_root=/tmp/project"]}>
      <Routes>
        <Route path="/pipeline-drafts/:draftId" element={<DraftGraphRoute />} />
      </Routes>
    </MemoryRouter>,
  );

  expect(await screen.findByRole("alert")).toHaveTextContent("DRAFT_NOT_FOUND");
});

test("keeps execute disabled and surfaces validation errors", async () => {
  vi.mocked(useNavigate).mockReturnValue(vi.fn());
  vi.mocked(api.getPipelineDraft).mockResolvedValue(makeDraftResponse({ draftHash: "h1" }));
  vi.mocked(api.validatePipelineDraft).mockRejectedValue(
    Object.assign(new Error("VALIDATION_REQUIRED"), { status: 409 }),
  );

  render(
    <MemoryRouter initialEntries={["/pipeline-drafts/draft_1?project_root=/tmp/project"]}>
      <Routes>
        <Route path="/pipeline-drafts/:draftId" element={<DraftGraphRoute />} />
      </Routes>
    </MemoryRouter>,
  );

  await screen.findByText("Input Dataset");
  fireEvent.click(screen.getByRole("button", { name: "Validate" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("VALIDATION_REQUIRED");
  expect(screen.getByRole("button", { name: "Execute Draft" })).toBeDisabled();
});

test("keeps the draft open and surfaces execute errors", async () => {
  vi.mocked(useNavigate).mockReturnValue(vi.fn());
  vi.mocked(api.getPipelineDraft).mockResolvedValue(makeDraftResponse({ draftHash: "h1" }));
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
  vi.mocked(api.executePipelineDraft).mockRejectedValue(
    Object.assign(new Error("VALIDATED_DRAFT_HASH_MISMATCH"), { status: 409 }),
  );

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

  expect(await screen.findByRole("alert")).toHaveTextContent("VALIDATED_DRAFT_HASH_MISMATCH");
  expect(screen.getByText("Draft Graph")).toBeInTheDocument();
});

test("shows a back link to the source run lineage (P6)", async () => {
  const navigate = vi.fn();
  vi.mocked(useNavigate).mockReturnValue(navigate);
  vi.mocked(api.getPipelineDraft).mockResolvedValue(makeDraftResponse());

  render(
    <MemoryRouter initialEntries={["/pipeline-drafts/draft_1?project_root=/tmp/project"]}>
      <Routes>
        <Route path="/pipeline-drafts/:draftId" element={<DraftGraphRoute />} />
      </Routes>
    </MemoryRouter>,
  );

  const back = await screen.findByRole("button", { name: /back to lineage/i });
  fireEvent.click(back);
  expect(navigate).toHaveBeenCalledWith(
    "/runs/run_parent?project_root=%2Ftmp%2Fproject&tab=lineage",
  );
});

test("uses the persisted Genesis execution mode and returns to the parent Graph", async () => {
  const navigate = vi.fn();
  vi.mocked(useNavigate).mockReturnValue(navigate);
  vi.mocked(api.getPipelineDraft).mockResolvedValue(makeGenesisDraftResponse());
  vi.mocked(api.validatePipelineDraft).mockResolvedValue({
    ok: true,
    status: "valid",
    executable: true,
    checks: [],
    resolved_execution: { execution_mode: "genesis", genesis: true },
    validated_execution_mode: "genesis",
    validated_draft_hash: "g1",
    validated_at: "",
  });
  vi.mocked(api.executePipelineDraft).mockResolvedValue({
    ok: true,
    run_id: "run_genesis",
    draft_id: "draft_genesis",
    executed_draft_hash: "g1",
    execution_mode: "genesis",
    produced_lineage: { genesis: true, execution_mode: "genesis" },
    focus: { status: "pending_index", run_id: "run_genesis", poll: { genesis: true, execution_mode: "genesis" } },
  });

  render(
    <MemoryRouter initialEntries={["/pipeline-drafts/draft_genesis?project_root=/tmp/project&return_to=%2Fp%2Fproject%2Fgraph%3Fview%3Dnotebook%26notebook%3Dnb_1"]}>
      <Routes>
        <Route path="/pipeline-drafts/:draftId" element={<DraftGraphRoute />} />
      </Routes>
    </MemoryRouter>,
  );

  const back = await screen.findByRole("button", { name: /back to lineage/i });
  expect(back).toBeEnabled();
  fireEvent.click(back);
  expect(navigate).toHaveBeenCalledWith("/p/project/graph?view=notebook&notebook=nb_1");

  fireEvent.click(screen.getByRole("button", { name: "Validate" }));
  await waitFor(() => expect(api.validatePipelineDraft).toHaveBeenCalledWith(
    "/tmp/project",
    "draft_genesis",
    "genesis",
  ));
  await waitFor(() => expect(screen.getByRole("button", { name: "Execute Draft" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "Execute Draft" }));
  await waitFor(() => expect(api.executePipelineDraft).toHaveBeenCalledWith(
    "/tmp/project",
    "draft_genesis",
    { validated_draft_hash: "g1", execution_mode: "genesis" },
  ));
});

test("reconciles a materialized Notebook option after the Draft run reaches terminal state", async () => {
  const navigate = vi.fn();
  vi.mocked(useNavigate).mockReturnValue(navigate);
  vi.mocked(api.getPipelineDraft).mockResolvedValue(makeGenesisDraftResponse());
  vi.mocked(api.validatePipelineDraft).mockResolvedValue({
    ok: true,
    status: "valid",
    executable: true,
    checks: [],
    resolved_execution: { execution_mode: "genesis", genesis: true },
    validated_execution_mode: "genesis",
    validated_draft_hash: "g1",
    validated_at: "",
  });
  vi.mocked(api.executePipelineDraft).mockResolvedValue({
    ok: true,
    run_id: "run_genesis",
    draft_id: "draft_genesis",
    executed_draft_hash: "g1",
    execution_mode: "genesis",
    produced_lineage: { genesis: true },
    focus: { status: "pending_index", run_id: "run_genesis", poll: { genesis: true } },
  });
  vi.mocked(api.waitForRunTerminal).mockResolvedValue({
    run_id: "run_genesis",
    status: "completed",
    mode: "auto",
    started_at: null,
    y: "outcome",
    x: ["treatment"],
    lineage: [],
    artifact_counts: { model_result: 1 },
    errors: { issues: [] },
  });
  vi.mocked(notebookApi.completeNotebookOptionExecution).mockResolvedValue({});

  render(
    <MemoryRouter initialEntries={["/pipeline-drafts/draft_genesis?project_root=/tmp/project"]}>
      <Routes>
        <Route path="/pipeline-drafts/:draftId" element={<DraftGraphRoute />} />
      </Routes>
    </MemoryRouter>,
  );

  await screen.findByText("Draft Graph");
  fireEvent.click(screen.getByRole("button", { name: "Validate" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Execute Draft" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "Execute Draft" }));

  await waitFor(() => expect(notebookApi.completeNotebookOptionExecution).toHaveBeenCalledWith(
    "/tmp/project",
    "nb_1",
    "opt_1",
    { run_id: "run_genesis" },
  ));
});
