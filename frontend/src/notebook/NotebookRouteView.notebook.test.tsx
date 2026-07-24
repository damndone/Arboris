import "@testing-library/jest-dom/vitest";
import { StrictMode } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { NotebookRouteView } from "./NotebookRouteView";
import { readCanonicalFixture } from "./fixtures/canonicalMocks";
import { uploadDataset } from "../api";
import {
  AgentSurfaceContext,
  type AgentSurfaceContextValue,
} from "../workbench/agent/AgentSurfaceContext";
import {
  useWorkbenchOptional,
  WorkbenchStateProvider,
} from "../workbench/WorkbenchStateProvider";
import {
  compileNotebookContext,
  ensureNotebookProjection,
  getNotebook,
  getNotebookTrace,
  listNotebooks,
  listNotebookOptions,
  materializeNotebookOption,
  proposeNotebookOptions,
  recordNotebookDecision,
} from "./notebookApi";

vi.mock("./notebookApi", () => ({
  compileNotebookContext: vi.fn(),
  ensureNotebookProjection: vi.fn(),
  getNotebook: vi.fn(),
  getNotebookTrace: vi.fn(),
  listNotebooks: vi.fn(),
  listNotebookOptions: vi.fn(),
  materializeNotebookOption: vi.fn(),
  proposeNotebookOptions: vi.fn(),
  recordNotebookDecision: vi.fn(),
}));

vi.mock("../api", () => ({
  uploadDataset: vi.fn(),
}));

function PanelProbe() {
  const workbench = useWorkbenchOptional();
  return <span data-testid="selected-bottom-panel">{workbench?.state.bottomPanel ?? "none"}</span>;
}

const context = {
  context_id: "ctx_1",
  context_profile: "notebook-plan/v1",
  generation_context_hash: "sha256:context",
  freshness_dependency_fingerprint: "fresh1:premises",
  artifact_type_counts: { time_series_json: 1 },
  omissions: [],
  budget_report: {
    sections: [],
    total_used_bytes: 100,
    total_budget_bytes: 1000,
  },
  source_manifest: [],
  trace: [],
};

describe("NotebookRouteView", () => {
  beforeEach(() => {
    vi.mocked(uploadDataset).mockResolvedValue({ sha256: "a".repeat(64), filename: "data.csv" });
    vi.mocked(ensureNotebookProjection).mockResolvedValue({
      notebook_id: "nb_1",
      run_family_id: "family_1",
      title: "Analysis",
      created_by: "user",
      active_head_run_id: null,
    });
    vi.mocked(getNotebook).mockResolvedValue({
      notebook_id: "nb_1",
      run_family_id: "family_1",
      title: "Analysis",
      created_by: "user",
      active_head_run_id: "run_head",
    });
    vi.mocked(compileNotebookContext).mockResolvedValue(context);
    vi.mocked(listNotebookOptions).mockResolvedValue({ context, options: [], trace_id: "trace_1" });
    vi.mocked(proposeNotebookOptions).mockResolvedValue({
      context,
      options: [],
      trace_id: "trace_1",
    });
    vi.mocked(getNotebookTrace).mockResolvedValue({ trace_id: "trace_1", events: [] });
    vi.mocked(listNotebooks).mockResolvedValue([]);
    vi.mocked(recordNotebookDecision).mockResolvedValue({});
  });

  it("creates a notebook, compiles context, proposes options, and renders the real surface", async () => {
    vi.mocked(proposeNotebookOptions).mockResolvedValue({
      context,
      options: [readCanonicalFixture("notebook_option_revision")],
      trace_id: "trace_1",
    });

    render(
      <StrictMode>
        <MemoryRouter initialEntries={["/p/project/graph?view=notebook"]}>
          <NotebookRouteView projectRoot="/tmp/project" activeRunId="run_head" />
        </MemoryRouter>
      </StrictMode>,
    );

    await waitFor(() => expect(screen.getByTestId("notebook-surface")).toHaveAttribute("data-state", "ready"));
    expect(screen.getByTestId("notebook-option-list")).toBeInTheDocument();
    expect(ensureNotebookProjection).toHaveBeenCalledOnce();
    expect(ensureNotebookProjection).toHaveBeenCalledWith("/tmp/project", {
      from_run_id: "run_head",
      created_by: "user",
      title: "Analysis Notebook",
    });
    expect(compileNotebookContext).toHaveBeenCalledWith("/tmp/project", "nb_1");
    expect(proposeNotebookOptions).toHaveBeenCalledWith("/tmp/project", "nb_1", 3);
  });

  it("renders a typed API failure without pretending the notebook is empty", async () => {
    vi.mocked(ensureNotebookProjection).mockRejectedValue(
      Object.assign(new Error("project missing"), { code: "PROJECT_NOT_FOUND" }),
    );

    render(
      <MemoryRouter initialEntries={["/p/project/graph?view=notebook"]}>
        <NotebookRouteView projectRoot="/tmp/project" activeRunId="run_head" />
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByTestId("notebook-surface")).toHaveAttribute("data-state", "error"));
    expect(screen.getByTestId("notebook-error")).toHaveTextContent("PROJECT_NOT_FOUND");
    expect(screen.queryByTestId("notebook-empty")).toBeNull();
  });

  it("uploads a zero-run dataset and binds the Notebook to the verified upload", async () => {
    render(
      <MemoryRouter initialEntries={["/p/project/graph?view=notebook"]}>
        <NotebookRouteView projectRoot="/tmp/project" />
      </MemoryRouter>,
    );

    expect(screen.getByTestId("notebook-dataset-start")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Dataset"), {
      target: { files: [new File(["outcome,predictor\n1,2"], "data.csv", { type: "text/csv" })] },
    });

    await waitFor(() => expect(ensureNotebookProjection).toHaveBeenCalledWith("/tmp/project", {
      dataset: {
        upload_sha256: "a".repeat(64),
        filename: "data.csv",
        sheet_names: [],
      },
      created_by: "user",
      title: "Analysis Notebook",
    }));
  });

  it("reuses the sole persisted Notebook when Graph reload has no active Run", async () => {
    vi.mocked(listNotebooks).mockResolvedValue([
      {
        notebook_id: "nb_1",
        run_family_id: "family_1",
        title: "Analysis",
        created_by: "user",
        active_head_run_id: null,
      },
    ]);
    vi.mocked(listNotebookOptions).mockResolvedValue({
      context,
      options: [],
      trace_id: "trace_1",
    });

    render(
      <MemoryRouter initialEntries={["/p/project/graph?view=notebook"]}>
        <NotebookRouteView projectRoot="/tmp/project" />
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByTestId("notebook-surface")).toHaveAttribute("data-state", "empty"));
    expect(listNotebooks).toHaveBeenCalledWith("/tmp/project");
    expect(screen.getByTestId("notebook-surface")).toHaveTextContent("Analysis");
  });

  it("reuses the sole persisted Notebook when a Workbench remount still has an active Run", async () => {
    vi.mocked(ensureNotebookProjection).mockClear();
    vi.mocked(listNotebooks).mockClear();
    vi.mocked(listNotebooks).mockResolvedValue([
      {
        notebook_id: "nb_1",
        run_family_id: "family_1",
        title: "Analysis",
        created_by: "user",
        active_head_run_id: "run_head",
      },
    ]);
    vi.mocked(listNotebookOptions).mockResolvedValue({
      context,
      options: [],
      trace_id: "trace_1",
    });

    render(
      <MemoryRouter initialEntries={["/p/project/graph?view=notebook"]}>
        <NotebookRouteView projectRoot="/tmp/project" activeRunId="run_head" />
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByTestId("notebook-surface")).toHaveAttribute("data-state", "empty"));
    expect(listNotebooks).toHaveBeenCalledWith("/tmp/project");
    expect(ensureNotebookProjection).not.toHaveBeenCalled();
    expect(screen.getByTestId("notebook-surface")).toHaveTextContent("nb_1");
  });

  it("opens Draft confirmation for an already-selected materializable option without reselecting it", async () => {
    const selected = readCanonicalFixture("notebook_option_revision_v11");
    selected.lifecycle_status = "selected";
    vi.mocked(proposeNotebookOptions).mockResolvedValue({
      context,
      options: [selected],
      trace_id: "trace_1",
    });

    render(
      <MemoryRouter initialEntries={["/p/project/graph?view=notebook"]}>
        <NotebookRouteView projectRoot="/tmp/project" activeRunId="run_head" />
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByTestId("option-execute")).toBeEnabled());
    fireEvent.click(screen.getByTestId("option-execute"));

    expect(await screen.findByTestId("notebook-confirmation")).toBeInTheDocument();
    expect(recordNotebookDecision).not.toHaveBeenCalledWith(
      expect.anything(),
      expect.anything(),
      expect.objectContaining({ decision: "selected" }),
    );
  });

  it("keeps the selected option in local state after Review so a retry opens confirmation idempotently", async () => {
    const proposed = readCanonicalFixture("notebook_option_revision_v11");
    proposed.lifecycle_status = "proposed";
    const selected = { ...proposed, lifecycle_status: "selected" as const };
    vi.mocked(proposeNotebookOptions).mockResolvedValue({
      context,
      options: [proposed],
      trace_id: "trace_1",
    });
    vi.mocked(recordNotebookDecision).mockResolvedValue(selected);

    render(
      <MemoryRouter initialEntries={["/p/project/graph?view=notebook"]}>
        <NotebookRouteView projectRoot="/tmp/project" activeRunId="run_head" />
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByTestId("option-execute")).toBeEnabled());
    fireEvent.click(screen.getByTestId("option-execute"));
    await waitFor(() =>
      expect(screen.getByTestId(`option-card-${proposed.option_id}`)).toHaveAttribute(
        "data-lifecycle",
        "selected",
      ),
    );

    vi.mocked(recordNotebookDecision).mockClear();
    fireEvent.click(screen.getByTestId("option-execute"));
    expect(await screen.findByTestId("notebook-confirmation")).toBeInTheDocument();
    expect(recordNotebookDecision).not.toHaveBeenCalled();
  });

  it("cancels Draft confirmation without silently deferring the selected option", async () => {
    const selected = readCanonicalFixture("notebook_option_revision_v11");
    selected.lifecycle_status = "selected";
    vi.mocked(proposeNotebookOptions).mockResolvedValue({
      context,
      options: [selected],
      trace_id: "trace_1",
    });

    render(
      <MemoryRouter initialEntries={["/p/project/graph?view=notebook"]}>
        <NotebookRouteView projectRoot="/tmp/project" activeRunId="run_head" />
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByTestId("option-execute")).toBeEnabled());
    fireEvent.click(screen.getByTestId("option-execute"));
    fireEvent.click(await screen.findByTestId("confirmation-cancel"));

    await waitFor(() => expect(screen.queryByTestId("notebook-confirmation")).toBeNull());
    expect(recordNotebookDecision).not.toHaveBeenCalledWith(
      expect.anything(),
      expect.anything(),
      expect.objectContaining({ decision: "deferred" }),
    );
  });

  it("replans persisted options only after an explicit user action", async () => {
    const proposed = readCanonicalFixture("notebook_option_revision_v11");
    vi.mocked(proposeNotebookOptions).mockClear();
    vi.mocked(proposeNotebookOptions).mockResolvedValue({
      context,
      options: [proposed],
      trace_id: "trace_1",
    });

    render(
      <MemoryRouter initialEntries={["/p/project/graph?view=notebook"]}>
        <NotebookRouteView projectRoot="/tmp/project" activeRunId="run_head" />
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByTestId("notebook-option-list")).toBeInTheDocument());
    expect(proposeNotebookOptions).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByTestId("notebook-replan-options"));

    await waitFor(() => expect(proposeNotebookOptions).toHaveBeenCalledTimes(2));
  });

  it("hydrates the persisted Draft handoff after the route reloads", async () => {
    const materialized = readCanonicalFixture("notebook_option_revision_v11");
    materialized.lifecycle_status = "materialized";
    const materialization = {
      contract_version: "1.0",
      materialization_id: "mat_genesis_01",
      option_id: materialized.option_id,
      option_revision: materialized.option_revision,
      proposal_id: materialized.typed_proposal_id,
      proposal_revision: materialized.typed_proposal_revision,
      freshness_dependency_fingerprint: materialized.freshness_dependency_fingerprint,
      generation_context_id: materialized.generation_context_hash,
      draft_id: "draft_genesis_01",
      draft_hash: "sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
      draft_execution_mode: "genesis",
      source_run_id: null,
      source_model_node_id: null,
      source_op_node_id: null,
      source_node_hash: null,
      source_forest_node_key: null,
      source_context_fingerprint: null,
      dataset_upload_sha256: "sha256:1111111111111111111111111111111111111111111111111111111111111111",
      run_family_id: "family_1",
    };
    vi.mocked(listNotebookOptions).mockResolvedValue({
      context,
      options: [materialized],
      materializations: { [materialized.option_id as string]: materialization },
      trace_id: "trace_1",
    });

    render(
      <MemoryRouter initialEntries={["/p/project/graph?view=notebook&notebook=nb_1"]}>
        <NotebookRouteView projectRoot="/tmp/project" />
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByTestId("notebook-draft-handoff")).toBeInTheDocument());
    expect(screen.getByTestId("notebook-draft-handoff")).toHaveTextContent("draft_genesis_01");
    expect(screen.getByTestId("notebook-draft-handoff")).toHaveTextContent("Draft prepared");
  });

  it("hydrates the newest materialized sibling rather than the first option by id", async () => {
    const older = readCanonicalFixture("notebook_option_revision_v11") as Record<string, unknown>;
    const newer = {
      ...older,
      option_id: "opt_newer",
      created_at: "2026-07-24T02:00:00+00:00",
      lifecycle_status: "materialized",
    };
    older.option_id = "opt_older";
    older.created_at = "2026-07-23T02:00:00+00:00";
    older.lifecycle_status = "materialized";
    const materialization = (optionId: string, draftId: string) => ({
      contract_version: "1.0",
      materialization_id: `mat_${draftId}`,
      option_id: optionId,
      option_revision: 1,
      proposal_id: "prop_51de90",
      proposal_revision: 1,
      freshness_dependency_fingerprint: "fresh1:x",
      generation_context_id: "ctx_1",
      draft_id: draftId,
      draft_hash: "sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
      draft_execution_mode: "genesis",
      source_run_id: null,
      source_model_node_id: null,
      source_op_node_id: null,
      source_node_hash: null,
      source_forest_node_key: null,
      source_context_fingerprint: null,
      dataset_upload_sha256: "sha256:1111111111111111111111111111111111111111111111111111111111111111",
      run_family_id: "family_1",
    });
    vi.mocked(listNotebookOptions).mockResolvedValue({
      context,
      options: [older, newer],
      materializations: {
        opt_older: materialization("opt_older", "draft_old"),
        opt_newer: materialization("opt_newer", "draft_new"),
      },
      trace_id: "trace_1",
    });

    render(
      <MemoryRouter initialEntries={["/p/project/graph?view=notebook&notebook=nb_1"]}>
        <NotebookRouteView projectRoot="/tmp/project" />
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByTestId("notebook-draft-handoff")).toBeInTheDocument());
    expect(screen.getByTestId("notebook-draft-handoff")).toHaveTextContent("draft_new");
    expect(screen.getByTestId("notebook-draft-handoff")).not.toHaveTextContent("draft_old");
  });

  it("hydrates a generic execution result after a reload without requiring an ETS result parser", async () => {
    const executed = readCanonicalFixture("notebook_option_revision_v11");
    executed.lifecycle_status = "executed";
    vi.mocked(listNotebookOptions).mockResolvedValue({
      context,
      options: [executed],
      execution_results: {
        [executed.option_id as string]: {
          option_id: executed.option_id,
          option_revision: executed.option_revision,
          run_id: "run_arma_001",
          execution_status: "succeeded",
          committed: true,
          artifact_validation: {
            contract_profile: "artifact-identity-type-count/v1",
            validation_status: "passed",
            checked_dimensions: ["artifact_id", "artifact_type", "count", "step"],
            not_evaluated_dimensions: ["payload_schema"],
            issues: [],
          },
        },
      },
      trace_id: "trace_1",
    });

    render(
      <MemoryRouter initialEntries={["/p/project/graph?view=notebook&notebook=nb_1"]}>
        <NotebookRouteView projectRoot="/tmp/project" />
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByTestId("notebook-execution-summary")).toBeInTheDocument());
    expect(screen.getByTestId("notebook-execution-summary")).toHaveTextContent(
      "run_arma_001",
    );
    expect(screen.getByTestId("notebook-execution-summary")).toHaveTextContent(
      "output contract passed",
    );
  });

  it("turns selected narrative text into an editable next-question composer", async () => {
    render(
      <MemoryRouter initialEntries={["/p/project/graph?view=notebook"]}>
        <NotebookRouteView projectRoot="/tmp/project" activeRunId="run_head" />
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByTestId("notebook-surface")).toHaveAttribute("data-state", "empty"));
    vi.spyOn(window, "getSelection").mockReturnValue({
      toString: () => "a selected claim",
    } as unknown as Selection);
    fireEvent.mouseUp(screen.getByTestId("narrative-nb_1:title"));

    expect(screen.getByTestId("notebook-selection-actions")).toHaveTextContent("a selected claim");
    fireEvent.click(screen.getByTestId("selection-action-more-details"));
    expect(screen.getByTestId("notebook-selection-composer")).toBeInTheDocument();
    expect(screen.getByLabelText("Selected text question")).toHaveValue(
      'Explain the selected passage and cite the source:\n\n"a selected claim"\nSource: narrative:nb_1:title\n\n',
    );
    vi.restoreAllMocks();
  });

  it("opens the Agent side chat for the Codex-style side-chat action", async () => {
    const setPrompt = vi.fn();
    const agent = { setPrompt } as unknown as AgentSurfaceContextValue;
    render(
      <MemoryRouter initialEntries={["/p/project/graph?view=notebook"]}>
        <WorkbenchStateProvider runId="run_1">
          <AgentSurfaceContext.Provider value={agent}>
            <PanelProbe />
        <NotebookRouteView projectRoot="/tmp/project" activeRunId="run_head" />
          </AgentSurfaceContext.Provider>
        </WorkbenchStateProvider>
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByTestId("notebook-surface")).toHaveAttribute("data-state", "empty"));
    vi.spyOn(window, "getSelection").mockReturnValue({
      toString: () => "a selected claim",
    } as unknown as Selection);
    fireEvent.mouseUp(screen.getByTestId("narrative-nb_1:title"));
    fireEvent.click(screen.getByTestId("selection-action-side-chat"));

    expect(screen.getByTestId("selected-bottom-panel")).toHaveTextContent("agent");
    expect(setPrompt).toHaveBeenLastCalledWith(
      'Answer this targeted follow-up about the selected passage:\n\n"a selected claim"\nSource: narrative:nb_1:title\n\n',
    );
    vi.restoreAllMocks();
  });
});
