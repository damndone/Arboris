import "@testing-library/jest-dom/vitest";
import { StrictMode } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
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
import { ForestContext } from "../workbench/ForestContext";
import type { ForestViewModel } from "../lineage/api/graphViewTypes";
import {
  cancelNotebookPlanning,
  compileNotebookContext,
  confirmNotebookOption,
  ensureNotebookDatasetProjection,
  ensureNotebookProjection,
  getNotebook,
  getNotebookTrace,
  listNotebooks,
  listNotebookOptions,
  proposeNotebookOptions,
  recordNotebookDecision,
  updateNotebookFocus,
  type NotebookMaterializationResponse,
} from "./notebookApi";

vi.mock("./notebookApi", () => ({
  cancelNotebookPlanning: vi.fn(),
  compileNotebookContext: vi.fn(),
  confirmNotebookOption: vi.fn(),
  ensureNotebookDatasetProjection: vi.fn(),
  ensureNotebookProjection: vi.fn(),
  getNotebook: vi.fn(),
  getNotebookTrace: vi.fn(),
  listNotebooks: vi.fn(),
  listNotebookOptions: vi.fn(),
  proposeNotebookOptions: vi.fn(),
  recordNotebookDecision: vi.fn(),
  updateNotebookFocus: vi.fn(),
}));

vi.mock("../api", () => ({
  uploadDataset: vi.fn(),
}));

function PanelProbe() {
  const workbench = useWorkbenchOptional();
  return <span data-testid="selected-bottom-panel">{workbench?.state.bottomPanel ?? "none"}</span>;
}

function LocationProbe() {
  const location = useLocation();
  return (
    <span data-testid="location-search">
      {JSON.stringify(Object.fromEntries(new URLSearchParams(location.search)))}
    </span>
  );
}

function genesisMaterializationResponse() {
  const draftHash = `sha256:${"d".repeat(64)}`;
  return {
    draft: {
      draft_id: "draft_genesis_01",
    } as unknown as NotebookMaterializationResponse["draft"],
    draft_hash: draftHash,
    materialization: {
      contract_version: "1.0",
      materialization_id: "mat_genesis_01",
      option_id: "opt_7f3a1c",
      option_revision: 2,
      proposal_id: "prop_51de90",
      proposal_revision: 1,
      freshness_dependency_fingerprint: "fresh1:premises",
      generation_context_id: "ctx_1",
      draft_id: "draft_genesis_01",
      draft_hash: draftHash,
      draft_execution_mode: "genesis",
      source_run_id: null,
      source_model_node_id: null,
      source_op_node_id: null,
      source_node_hash: null,
      source_forest_node_key: null,
      source_context_fingerprint: null,
      dataset_upload_sha256: `sha256:${"1".repeat(64)}`,
      run_family_id: "family_1",
    },
    trace_id: "trace_materialize",
  };
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
    vi.resetAllMocks();
    vi.mocked(uploadDataset).mockResolvedValue({ sha256: "a".repeat(64), filename: "data.csv" });
    vi.mocked(ensureNotebookProjection).mockResolvedValue({
      notebook_id: "nb_1",
      run_family_id: "family_1",
      title: "Analysis",
      created_by: "user",
      active_head_run_id: null,
      user_focus: { goal: "Compare the available analysis options." },
    });
    vi.mocked(ensureNotebookDatasetProjection).mockResolvedValue({
      notebook_id: "nb_dataset",
      run_family_id: "family_dataset",
      title: "New analysis from source data",
      created_by: "user",
      active_head_run_id: null,
      user_focus: {},
    });
    vi.mocked(getNotebook).mockResolvedValue({
      notebook_id: "nb_1",
      run_family_id: "family_1",
      title: "Analysis",
      created_by: "user",
      active_head_run_id: "run_head",
      user_focus: { goal: "Compare the available analysis options." },
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
    vi.mocked(updateNotebookFocus).mockResolvedValue({
      notebook_id: "nb_1",
      run_family_id: "family_1",
      title: "Analysis",
      created_by: "user",
      active_head_run_id: "run_head",
      user_focus: { goal: "Compare the available analysis options." },
    });
    vi.mocked(cancelNotebookPlanning).mockResolvedValue({
      attempt_id: "attempt-test",
      status: "cancelled",
    });
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

    await waitFor(() => expect(screen.getByTestId("notebook-route-view")).toBeInTheDocument());
    expect(screen.getByTestId("notebook-option-list")).toBeInTheDocument();
    expect(ensureNotebookProjection).toHaveBeenCalledOnce();
    expect(ensureNotebookProjection).toHaveBeenCalledWith("/tmp/project", {
      from_run_id: "run_head",
      created_by: "user",
      title: "Analysis Notebook",
    });
    expect(compileNotebookContext).toHaveBeenCalledWith("/tmp/project", "nb_1");
    expect(proposeNotebookOptions).toHaveBeenCalledWith(
      "/tmp/project",
      "nb_1",
      3,
      {
        attemptId: expect.stringMatching(/^attempt_/),
        signal: expect.any(AbortSignal),
      },
    );
  });

  it("accepts a valid v2 domain-memory projection when no memory is eligible", async () => {
    const memoryContext = {
      ...context,
      domain_memory_projection: {
        contract_version: "domain-memory-context-input/v2" as const,
        retrieval_ref: "retrieval-memory-empty",
        scope_ref: "scope-memory-private",
        outcome: "empty" as const,
        reason: "no_eligible_memory",
        entries: [],
        omissions: [{
          memory_id: "memory-unadjusted",
          revision: 1,
          reason: "predicate_mismatch",
        }],
        bounded: true,
        preference_ref: "preference-memory",
        memory_authority: "non_authoritative" as const,
      },
    };
    vi.mocked(compileNotebookContext).mockResolvedValue(memoryContext);
    vi.mocked(listNotebookOptions).mockResolvedValue({
      context: memoryContext,
      options: [],
      trace_id: "trace_memory_empty",
    });
    vi.mocked(proposeNotebookOptions).mockResolvedValue({
      context: memoryContext,
      options: [],
      trace_id: "trace_memory_empty",
    });

    render(
      <MemoryRouter initialEntries={["/p/project/graph?view=notebook"]}>
        <NotebookRouteView projectRoot="/tmp/project" activeRunId="run_head" />
      </MemoryRouter>,
    );

    await waitFor(() =>
      expect(screen.getByTestId("notebook-surface")).toHaveAttribute("data-state", "empty"),
    );
    expect(screen.queryByTestId("notebook-error")).toBeNull();
  });

  it("opens shared Settings through a navigation intent instead of local memory switches", async () => {
    render(
      <MemoryRouter initialEntries={["/p/project/graph?view=notebook"]}>
        <NotebookRouteView projectRoot="/tmp/project" activeRunId="run_head" />
        <LocationProbe />
      </MemoryRouter>,
    );

    await screen.findByTestId("notebook-manage-memory");
    fireEvent.click(screen.getByTestId("notebook-manage-memory"));

    expect(screen.getByTestId("location-search")).toHaveTextContent('"memory_settings":"1"');
    expect(screen.getByTestId("location-search")).not.toHaveTextContent("domain_memory_use");
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

  it("does not ask the planner for options until the user has described the goal", async () => {
    vi.mocked(getNotebook).mockResolvedValue({
      notebook_id: "nb_1",
      run_family_id: "family_1",
      title: "Analysis",
      created_by: "user",
      active_head_run_id: "run_head",
      user_focus: {},
    });

    render(
      <MemoryRouter initialEntries={["/p/project/graph?view=notebook&notebook=nb_1"]}>
        <NotebookRouteView projectRoot="/tmp/project" activeRunId="run_head" />
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByTestId("notebook-surface")).toHaveAttribute("data-state", "empty"));
    expect(proposeNotebookOptions).not.toHaveBeenCalled();

    expect(screen.getByTestId("notebook-submit-intent")).toBeDisabled();
    expect(proposeNotebookOptions).not.toHaveBeenCalled();
  });

  it("uploads a zero-run dataset and binds the Notebook to the verified upload", async () => {
    render(
      <MemoryRouter initialEntries={["/p/project/graph?view=notebook"]}>
        <NotebookRouteView projectRoot="/tmp/project" />
      </MemoryRouter>,
    );

    expect(screen.getByTestId("notebook-dataset-start")).toBeInTheDocument();
    expect(screen.getByTestId("notebook-dataset-start")).toHaveTextContent(
      "same project data store",
    );
    expect(screen.getByTestId("notebook-dataset-start")).toHaveTextContent(
      "does not create a Run",
    );
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

  it("starts a fresh dataset-rooted Notebook from the header's New analysis menu", async () => {
    render(
      <MemoryRouter initialEntries={["/p/project/graph?view=notebook&notebook=nb_1"]}>
        <NotebookRouteView projectRoot="/tmp/project" activeRunId="run_head" />
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByTestId("notebook-route-view")).toBeInTheDocument());
    expect(screen.queryByTestId("notebook-source-restart")).toBeNull();
    fireEvent.click(screen.getByTestId("notebook-new-analysis-menu"));
    fireEvent.click(screen.getByTestId("notebook-start-from-source"));

    await waitFor(() =>
      expect(ensureNotebookDatasetProjection).toHaveBeenCalledWith("/tmp/project", {
        from_run_id: "run_head",
        created_by: "user",
        title: "New analysis from source data",
      }),
    );
  });

  it("deduplicates planning after a StrictMode runless upload binds the notebook URL", async () => {
    vi.mocked(proposeNotebookOptions).mockClear();
    let resolvePlanning: (value: {
      context: typeof context;
      options: unknown[];
      trace_id: string;
    }) => void = () => {};
    const planning = new Promise<{
      context: typeof context;
      options: unknown[];
      trace_id: string;
    }>((resolve) => {
      resolvePlanning = resolve;
    });
    vi.mocked(proposeNotebookOptions).mockImplementation(() => planning);

    render(
      <StrictMode>
        <MemoryRouter initialEntries={["/p/project/graph?view=notebook"]}>
          <NotebookRouteView projectRoot="/tmp/project-dedupe" />
        </MemoryRouter>
      </StrictMode>,
    );

    fireEvent.change(screen.getByLabelText("Dataset"), {
      target: { files: [new File(["outcome,predictor\n1,2"], "data.csv", { type: "text/csv" })] },
    });

    await waitFor(() => expect(proposeNotebookOptions).toHaveBeenCalledTimes(1));
    const proposed = readCanonicalFixture("notebook_option_revision");
    vi.mocked(listNotebookOptions).mockResolvedValue({
      context,
      options: [proposed],
      trace_id: "trace_1",
    });
    resolvePlanning({
      context,
      options: [proposed],
      trace_id: "trace_1",
    });
    await waitFor(() =>
      expect(screen.getByTestId("notebook-option-list")).toBeInTheDocument(),
    );
    expect(proposeNotebookOptions).toHaveBeenCalledTimes(1);
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

  it("lets the user choose among durable Notebooks when no active Run is available", async () => {
    const durableNotebooks = [
      {
        notebook_id: "nb_older",
        run_family_id: "family_older",
        title: "Earlier analysis",
        created_by: "user",
        active_head_run_id: "run_older",
      },
      {
        notebook_id: "nb_current",
        run_family_id: "family_current",
        title: "Current analysis",
        created_by: "user",
        active_head_run_id: "run_current",
      },
    ];
    vi.mocked(listNotebooks).mockResolvedValue(durableNotebooks);
    vi.mocked(getNotebook).mockImplementation(async (_projectRoot, requestedNotebookId) => {
      const notebook = durableNotebooks.find(
        (item) => item.notebook_id === requestedNotebookId,
      );
      if (!notebook) throw new Error(`missing notebook ${requestedNotebookId}`);
      return notebook;
    });

    render(
      <MemoryRouter initialEntries={["/p/project/graph?view=notebook"]}>
        <LocationProbe />
        <NotebookRouteView projectRoot="/tmp/project" />
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByTestId("notebook-route-chooser")).toBeInTheDocument());
    expect(screen.queryByTestId("notebook-error")).toBeNull();
    fireEvent.click(screen.getByTestId("notebook-choice-nb_current"));

    await waitFor(() =>
      expect(compileNotebookContext).toHaveBeenCalledWith("/tmp/project", "nb_current"),
    );
    expect(screen.getByTestId("location-search")).toHaveTextContent('"notebook":"nb_current"');
  });

  it("falls back to durable Notebook choices when automatic projection is rejected", async () => {
    vi.mocked(listNotebooks).mockResolvedValue([
      {
        notebook_id: "nb_a",
        run_family_id: "family_a",
        title: "Analysis A",
        created_by: "user",
        active_head_run_id: "run_a",
      },
      {
        notebook_id: "nb_b",
        run_family_id: "family_b",
        title: "Analysis B",
        created_by: "user",
        active_head_run_id: "run_b",
      },
    ]);
    vi.mocked(ensureNotebookProjection).mockRejectedValue(
      Object.assign(new Error("projection unavailable"), {
        code: "NOTEBOOK_REQUEST_INVALID",
      }),
    );

    render(
      <MemoryRouter initialEntries={["/p/project/graph?view=notebook"]}>
        <NotebookRouteView projectRoot="/tmp/project" activeRunId="run_current" />
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByTestId("notebook-route-chooser")).toBeInTheDocument());
    expect(screen.queryByTestId("notebook-error")).toBeNull();
  });

  it("recovers a stale Notebook URL to the sole persisted project Notebook", async () => {
    vi.mocked(getNotebook).mockRejectedValue(
      Object.assign(new Error("Notebook no longer exists"), { code: "NOTEBOOK_NOT_FOUND" }),
    );
    vi.mocked(listNotebooks).mockResolvedValue([
      {
        notebook_id: "nb_current",
        run_family_id: "family_1",
        title: "Current analysis",
        created_by: "user",
        active_head_run_id: "run_head",
        user_focus: {},
      },
    ]);

    render(
      <MemoryRouter initialEntries={["/p/project/graph?view=notebook&notebook=nb_stale"]}>
        <LocationProbe />
        <NotebookRouteView projectRoot="/tmp/project" activeRunId="run_head" />
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByTestId("notebook-surface")).toHaveAttribute("data-state", "empty"));
    expect(listNotebooks).toHaveBeenCalledWith("/tmp/project");
    expect(compileNotebookContext).toHaveBeenCalledWith("/tmp/project", "nb_current");
    expect(screen.getByTestId("location-search")).toHaveTextContent('"notebook":"nb_current"');
    expect(screen.queryByTestId("notebook-error")).toBeNull();
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

  it("opens the prepared genesis Draft in Graph after materialization succeeds", async () => {
    const selected = readCanonicalFixture("notebook_option_revision_v11");
    selected.lifecycle_status = "selected";
    vi.mocked(listNotebookOptions).mockResolvedValue({
      context,
      options: [selected],
      trace_id: "trace_1",
    });
    vi.mocked(confirmNotebookOption).mockResolvedValue(
      genesisMaterializationResponse(),
    );
    const onMaterializedDraft = vi.fn();

    render(
      <MemoryRouter
        initialEntries={["/p/project/graph?view=notebook&notebook=nb_1"]}
      >
        <LocationProbe />
        <NotebookRouteView
          projectRoot="/tmp/project"
          onMaterializedDraft={onMaterializedDraft}
        />
      </MemoryRouter>,
    );

    await waitFor(() =>
      expect(screen.getByTestId("option-execute")).toHaveTextContent("Review plan"),
    );
    fireEvent.click(screen.getByTestId("option-execute"));
    fireEvent.click(await screen.findByTestId("confirmation-confirm"));

    await waitFor(() =>
      expect(screen.getByTestId("location-search")).toHaveTextContent(
        '"view":"graph"',
      ),
    );
    expect(screen.getByTestId("location-search")).toHaveTextContent(
      `"notebook":"${selected.notebook_id}"`,
    );
    expect(screen.getByTestId("location-search")).toHaveTextContent(
      '"panel":"agent"',
    );
    expect(screen.getByTestId("location-search")).toHaveTextContent(
      '"tabs":"draft:draft_genesis_01:model_1"',
    );
    expect(screen.getByTestId("location-search")).toHaveTextContent(
      '"active":"draft:draft_genesis_01:model_1"',
    );
    expect(screen.getByTestId("location-search")).toHaveTextContent(
      '"focus":"draft:draft_genesis_01:model_1"',
    );
    expect(confirmNotebookOption).toHaveBeenCalledWith(
      "/tmp/project",
      selected.notebook_id,
      selected.option_id,
      {
        option_revision: selected.option_revision,
        proposal_id: selected.typed_proposal_id,
        proposal_revision: selected.typed_proposal_revision,
      },
    );
    expect(onMaterializedDraft).toHaveBeenCalledOnce();
  });

  it("submits a normal confirmation to the server-owned confirmation endpoint", async () => {
    const selected = readCanonicalFixture("notebook_option_revision_v11");
    selected.lifecycle_status = "selected";
    vi.mocked(listNotebookOptions).mockResolvedValue({
      context,
      options: [selected],
      trace_id: "trace_1",
    });
    vi.mocked(confirmNotebookOption).mockResolvedValue({
      execution: {
        option_id: selected.option_id,
        option_revision: selected.option_revision,
        proposal_id: selected.typed_proposal_id,
        proposal_revision: selected.typed_proposal_revision,
      },
      outcome: {
        option_id: selected.option_id,
        option_revision: selected.option_revision,
        run_id: null,
        execution_status: "succeeded",
        artifact_validation: {
          contract_profile: "workflow",
          validation_status: "passed",
          checked_dimensions: [],
          not_evaluated_dimensions: [],
          issues: [],
        },
        active_head_advanced: false,
        lifecycle_status: "executed",
      },
      workflow_execution: {
        workflow_id: "workflow_1",
        plan_fingerprint: "plan_1",
        status: "completed",
        branch_runs: [],
        post_estimation_artifact_ids: [],
      },
      trace_id: "trace_2",
    });

    const refetch = vi.fn();
    render(
      <ForestContext.Provider
        value={{
          forest: {} as ForestViewModel,
          activeRunId: "run_head",
          setActiveRunId: vi.fn(),
          refetch,
        }}
      >
        <MemoryRouter initialEntries={["/p/project/graph?view=notebook&notebook=nb_1"]}>
          <NotebookRouteView projectRoot="/tmp/project" />
        </MemoryRouter>
      </ForestContext.Provider>,
    );

    await waitFor(() => expect(screen.getByTestId("option-execute")).toBeEnabled());
    fireEvent.click(screen.getByTestId("option-execute"));
    fireEvent.click(await screen.findByTestId("confirmation-confirm"));

    await waitFor(() =>
      expect(confirmNotebookOption).toHaveBeenCalledWith(
        "/tmp/project",
        selected.notebook_id,
        selected.option_id,
        {
          option_revision: selected.option_revision,
          proposal_id: selected.typed_proposal_id,
          proposal_revision: selected.typed_proposal_revision,
        },
      ),
    );
    await waitFor(() => expect(listNotebookOptions).toHaveBeenCalledTimes(2));
    expect(refetch).toHaveBeenCalledOnce();
    expect(proposeNotebookOptions).not.toHaveBeenCalled();
  });

  it("keeps the selected option and confirmation visible when Draft preparation fails", async () => {
    const selected = readCanonicalFixture("notebook_option_revision_v11");
    selected.lifecycle_status = "selected";
    vi.mocked(listNotebookOptions).mockResolvedValue({
      context,
      options: [selected],
      trace_id: "trace_1",
    });
    vi.mocked(confirmNotebookOption).mockRejectedValue(
      Object.assign(new Error("Draft validation rejected the proposal"), {
        code: "OPTION_MATERIALIZATION_FAILED",
      }),
    );

    render(
      <MemoryRouter initialEntries={["/p/project/graph?view=notebook&notebook=nb_1"]}>
        <NotebookRouteView projectRoot="/tmp/project" />
      </MemoryRouter>,
    );

    await waitFor(() =>
      expect(screen.getByTestId("option-execute")).toHaveTextContent("Review plan"),
    );
    fireEvent.click(screen.getByTestId("option-execute"));
    fireEvent.click(await screen.findByTestId("confirmation-confirm"));

    await waitFor(() =>
      expect(screen.getByTestId("notebook-action-error")).toHaveTextContent(
        "OPTION_MATERIALIZATION_FAILED",
      ),
    );
    expect(screen.getByTestId("notebook-action-error")).toHaveTextContent(
      "Draft validation rejected the proposal",
    );
    expect(screen.getByTestId("notebook-surface")).toHaveAttribute(
      "data-state",
      "confirmation",
    );
    expect(screen.getByTestId(`option-card-${selected.option_id}`)).toBeInTheDocument();
    expect(screen.getByTestId("notebook-confirmation")).toBeInTheDocument();
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

    fireEvent.click(screen.getByTestId("notebook-submit-intent"));

    await waitFor(() => expect(proposeNotebookOptions).toHaveBeenCalledTimes(2));
  });

  it("cancels replanning, preserves current options, and ignores a late response", async () => {
    const current = readCanonicalFixture("notebook_option_revision_v11");
    const late = {
      ...readCanonicalFixture("notebook_option_revision_v11"),
      option_id: "option_late",
    };
    vi.mocked(listNotebookOptions).mockResolvedValue({
      context,
      options: [current],
      trace_id: "trace_1",
    });
    let resolvePlanning: (value: {
      context: typeof context;
      options: unknown[];
      trace_id: string;
    }) => void = () => {};
    vi.mocked(proposeNotebookOptions).mockImplementation(
      () =>
        new Promise((resolve) => {
          resolvePlanning = resolve;
        }),
    );

    render(
      <MemoryRouter initialEntries={["/p/project/graph?view=notebook&notebook=nb_1"]}>
        <NotebookRouteView projectRoot="/tmp/project" />
      </MemoryRouter>,
    );

    await waitFor(() =>
      expect(screen.getByTestId(`option-card-${current.option_id}`)).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("notebook-submit-intent"));

    await waitFor(() =>
      expect(screen.getByTestId("notebook-planning-progress")).toBeInTheDocument(),
    );
    expect(screen.getByTestId(`option-card-${current.option_id}`)).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("notebook-cancel-planning"));

    await waitFor(() => expect(cancelNotebookPlanning).toHaveBeenCalledOnce());
    const attemptId = vi.mocked(cancelNotebookPlanning).mock.calls[0][2];
    expect(attemptId).toMatch(/^attempt_/);
    expect(screen.queryByTestId("notebook-planning-progress")).toBeNull();
    expect(screen.getByTestId(`option-card-${current.option_id}`)).toBeInTheDocument();

    resolvePlanning({ context, options: [late], trace_id: "trace_1" });
    await Promise.resolve();
    expect(screen.queryByTestId("option-card-option_late")).toBeNull();
    expect(screen.getByTestId(`option-card-${current.option_id}`)).toBeInTheDocument();
  });

  it("reports when backend cancellation cannot be confirmed", async () => {
    const current = readCanonicalFixture("notebook_option_revision_v11");
    vi.mocked(listNotebookOptions).mockResolvedValue({
      context,
      options: [current],
      trace_id: "trace_1",
    });
    vi.mocked(proposeNotebookOptions).mockImplementation(
      () => new Promise(() => {}),
    );
    vi.mocked(cancelNotebookPlanning).mockRejectedValue(
      Object.assign(new Error("cancel endpoint unavailable"), {
        code: "NETWORK_ERROR",
      }),
    );

    render(
      <MemoryRouter initialEntries={["/p/project/graph?view=notebook&notebook=nb_1"]}>
        <NotebookRouteView projectRoot="/tmp/project" />
      </MemoryRouter>,
    );

    await waitFor(() =>
      expect(screen.getByTestId(`option-card-${current.option_id}`)).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("notebook-submit-intent"));
    await waitFor(() =>
      expect(screen.getByTestId("notebook-planning-progress")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("notebook-cancel-planning"));

    await waitFor(() =>
      expect(screen.getByTestId("notebook-planning-error")).toHaveTextContent(
        "NOTEBOOK_PLANNING_CANCEL_FAILED",
      ),
    );
    expect(screen.getByTestId("notebook-planning-error")).toHaveTextContent(
      "backend cancellation was not confirmed",
    );
    expect(screen.getByTestId(`option-card-${current.option_id}`)).toBeInTheDocument();
  });

  it("keeps current options usable when a replan times out", async () => {
    const current = readCanonicalFixture("notebook_option_revision_v11");
    vi.mocked(listNotebookOptions).mockResolvedValue({
      context,
      options: [current],
      trace_id: "trace_1",
    });
    vi.mocked(proposeNotebookOptions).mockRejectedValue(
      Object.assign(new Error("Notebook planning provider exceeded 120s"), {
        code: "NOTEBOOK_PLANNING_TIMEOUT",
      }),
    );

    render(
      <MemoryRouter initialEntries={["/p/project/graph?view=notebook&notebook=nb_1"]}>
        <NotebookRouteView projectRoot="/tmp/project" />
      </MemoryRouter>,
    );

    await waitFor(() =>
      expect(screen.getByTestId(`option-card-${current.option_id}`)).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("notebook-submit-intent"));

    await waitFor(() =>
      expect(screen.getByTestId("notebook-planning-error")).toHaveTextContent(
        "NOTEBOOK_PLANNING_TIMEOUT",
      ),
    );
    expect(screen.getByTestId(`option-card-${current.option_id}`)).toBeInTheDocument();
    expect(screen.getByTestId("notebook-retry-planning")).toHaveTextContent("Retry");
  });

  it("preserves a locally rejected option when a later replan fails", async () => {
    const proposed = readCanonicalFixture("notebook_option_revision_v11");
    proposed.lifecycle_status = "proposed";
    const rejected = { ...proposed, lifecycle_status: "rejected" as const };
    vi.mocked(listNotebookOptions).mockResolvedValue({
      context,
      options: [proposed],
      trace_id: "trace_1",
    });
    vi.mocked(recordNotebookDecision).mockResolvedValue(rejected);
    vi.mocked(proposeNotebookOptions).mockRejectedValue(
      Object.assign(new Error("Notebook planning provider rejected the payload"), {
        code: "NOTEBOOK_PLANNING_CONTRACT_INVALID",
      }),
    );

    render(
      <MemoryRouter initialEntries={["/p/project/graph?view=notebook&notebook=nb_1"]}>
        <NotebookRouteView projectRoot="/tmp/project" />
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByTestId("option-reject")).toBeEnabled());
    fireEvent.click(screen.getByTestId("option-reject"));
    await waitFor(() =>
      expect(screen.getByTestId(`option-card-${proposed.option_id}`)).toHaveAttribute(
        "data-lifecycle",
        "rejected",
      ),
    );

    fireEvent.click(screen.getByTestId("notebook-submit-intent"));
    await waitFor(() =>
      expect(screen.getByTestId("notebook-planning-error")).toHaveTextContent(
        "NOTEBOOK_PLANNING_CONTRACT_INVALID",
      ),
    );
    expect(screen.getByTestId(`option-card-${proposed.option_id}`)).toHaveAttribute(
      "data-lifecycle",
      "rejected",
    );
  });

  it("runs agent revalidation when a stale option requests it", async () => {
    const stale = readCanonicalFixture("notebook_option_revision_v11");
    stale.freshness_status = "stale";
    vi.mocked(listNotebookOptions).mockResolvedValue({
      context,
      options: [stale],
      trace_id: "trace_1",
    });
    vi.mocked(proposeNotebookOptions).mockClear();
    let resolveRevalidation: (value: {
      context: typeof context;
      options: unknown[];
      trace_id: string;
    }) => void = () => {};
    vi.mocked(proposeNotebookOptions).mockImplementation(() => new Promise((resolve) => {
      resolveRevalidation = resolve;
    }));

    render(
      <MemoryRouter initialEntries={["/p/project/graph?view=notebook&notebook=nb_1"]}>
        <NotebookRouteView projectRoot="/tmp/project" />
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByTestId("option-revalidate")).toBeEnabled());
    fireEvent.click(screen.getByTestId("option-revalidate"));

    await waitFor(() => expect(proposeNotebookOptions).toHaveBeenCalledTimes(1));
    expect(screen.getByTestId("notebook-planning-progress")).toBeInTheDocument();
    resolveRevalidation({
      context,
      options: [{ ...stale, freshness_status: "fresh", option_revision: 3 }],
      trace_id: "trace_1",
    });
    await waitFor(() =>
      expect(screen.getByTestId(`option-card-${stale.option_id}`)).toHaveAttribute(
        "data-freshness",
        "fresh",
      ),
    );
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
