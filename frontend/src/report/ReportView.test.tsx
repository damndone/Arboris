import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { makeOwnerResolutionSeedFixture } from "../lineage/api/nodeOperationContext";
import { ReportView } from "./ReportView";

const mockForest = vi.hoisted(() => ({ current: null as unknown }));
const mockWb = vi.hoisted(() => ({ current: null as unknown }));
const mockGenerate = vi.hoisted(() => ({
  current: vi.fn() as ReturnType<typeof vi.fn>,
}));
const mockSaveAiReport = vi.hoisted(() => vi.fn());
const mockFetchAiReports = vi.hoisted(() => vi.fn());
const mockFigureArtifacts = vi.hoisted(() => ({ groups: [] as unknown[] }));
const mockFigureContext = vi.hoisted(() => vi.fn());
const mockArtifactJson = vi.hoisted(() => vi.fn());
const mockFigureArtifactsError = vi.hoisted(() => ({ current: null as Error | null }));

vi.mock("../workbench/ForestContext", () => ({
  useForest: () => mockForest.current,
}));
vi.mock("../workbench/WorkbenchStateProvider", () => ({
  useWorkbenchOptional: () => mockWb.current,
}));
vi.mock("./reportClient", async (importOriginal) => {
  const original = await importOriginal<typeof import("./reportClient")>();
  return {
    ...original,
    generateReport: (...args: unknown[]) => mockGenerate.current(...args),
    saveAiReport: (...args: unknown[]) => mockSaveAiReport(...args),
    fetchAiReports: (...args: unknown[]) => mockFetchAiReports(...args),
  };
});
vi.mock("../api", async (importOriginal) => {
  const original = await importOriginal<typeof import("../api")>();
  return {
    ...original,
    fetchRunArtifacts: () => mockFigureArtifactsError.current
      ? Promise.reject(mockFigureArtifactsError.current)
      : Promise.resolve(mockFigureArtifacts),
    fetchArtifactJson: (...args: unknown[]) => mockArtifactJson(...args),
  };
});
vi.mock("../workbench/views/figureAi", async (importOriginal) => {
  const original = await importOriginal<typeof import("../workbench/views/figureAi")>();
  return { ...original, fetchFigureAiContext: (...args: unknown[]) => mockFigureContext(...args) };
});

function seedForest() {
  const seed = makeOwnerResolutionSeedFixture();
  const model = seed.forest.nodes.find((n) => n.nodeKey === seed.sharedNodeKey)!;
  model.editableSchema = [
    { key: "covariance", kind: "select", label: "Covariance", value: "HC1" },
  ] as never;
  model.stats = { r_squared: 0.86 } as never;
  return seed;
}

describe("ReportView", () => {
  beforeEach(() => {
    const seed = seedForest();
    mockForest.current = { forest: seed.forest, activeRunId: "run_c", setActiveRunId: vi.fn() };
    mockWb.current = {
      state: {},
      dispatch: { setView: vi.fn(), selectByCanvasClick: vi.fn() },
    };
    mockGenerate.current = vi.fn();
    mockSaveAiReport.mockReset();
    mockFetchAiReports.mockReset();
    mockFetchAiReports.mockResolvedValue([]);
    mockFigureArtifacts.groups = [];
    mockFigureArtifactsError.current = null;
    mockFigureContext.mockReset();
    mockArtifactJson.mockReset();
  });

  it("shows the deterministic fact table before any AI call", () => {
    render(<ReportView />);
    expect(screen.getByTestId("report-fact-preview")).toBeInTheDocument();
    expect(screen.getByText("param:covariance")).toBeInTheDocument();
    expect(mockGenerate.current).not.toHaveBeenCalled();
  });

  it("loads bounded time-series artifacts into the citable fact table", async () => {
    mockFigureArtifacts.groups = [{
      artifact_type: "time_series_json",
      items: [
        { artifact_id: "ts.arma_selection", path: "artifacts/time_series/ts.arma_selection.json", artifact_type: "time_series_json" },
        { artifact_id: "ts.forecast_metrics", path: "artifacts/time_series/ts.forecast_metrics.json", artifact_type: "time_series_json" },
        { artifact_id: "ts.analysis_contract", path: "artifacts/time_series/ts.analysis_contract.json", artifact_type: "time_series_json" },
        { artifact_id: "ts.data_audit", path: "artifacts/time_series/ts.data_audit.json", artifact_type: "time_series_json" },
      ],
    }];
    mockArtifactJson.mockImplementation((_root, _run, artifactId) => {
      if (artifactId === "ts.arma_selection") {
        return Promise.resolve({ payload: { final_selected_candidate_id: "arma-p1-q1-n" } });
      }
      if (artifactId === "ts.analysis_contract") {
        return Promise.resolve({ payload: { transform: "log_return_pct" } });
      }
      if (artifactId === "ts.data_audit") {
        return Promise.resolve({ payload: { data_quality: { finite_value_count: 2542 } } });
      }
      return Promise.resolve({ payload: { rmse: 7.4, interval_coverage: 1 } });
    });

    render(<ReportView projectRoot="/tmp/projA" />);

    expect(await screen.findByText("ts:arma:selected_candidate")).toBeInTheDocument();
    expect(screen.getByText("ts:validation:rmse")).toBeInTheDocument();
    expect(screen.getByText("ts:contract:transform")).toBeInTheDocument();
    expect(screen.getByText("ts:data:analysis_observations")).toBeInTheDocument();
    expect(screen.getByText("arma-p1-q1-n")).toBeInTheDocument();
  });

  it("generate renders prose with verified chips and flags unknown ids", async () => {
    mockGenerate.current = vi.fn().mockResolvedValue({
      text: "R² 良好 [[c:c2]],而这个引用不存在 [[c:c99]]。",
      model: "deepseek-v4-flash",
    });
    render(<ReportView />);
    fireEvent.click(screen.getByRole("button", { name: /generate report/i }));

    await waitFor(() => expect(screen.getByTestId("report-body")).toBeInTheDocument());
    expect(screen.getByTestId("cite-chip")).toBeInTheDocument();
    expect(screen.getByTestId("cite-chip-unverified")).toBeInTheDocument();
    expect(screen.getByTestId("report-provenance").textContent).toContain(
      "deepseek-v4-flash",
    );
  });

  it("durably stores an AI report with its full fact snapshot when a project is open", async () => {
    mockGenerate.current = vi.fn().mockResolvedValue({ text: "Result [[c:c1]]", model: "deepseek-v4-pro" });
    render(<ReportView projectRoot="/tmp/projA" />);
    fireEvent.click(await screen.findByRole("button", { name: /generate report/i }));
    await waitFor(() => expect(mockSaveAiReport).toHaveBeenCalledTimes(1));
    expect(mockSaveAiReport.mock.calls[0][0]).toMatchObject({ projectRoot: "/tmp/projA", runId: "run_c" });
    expect(mockSaveAiReport.mock.calls[0][0].record.facts.length).toBeGreaterThan(0);
  });

  it("chip click jumps back to the graph and selects the node", async () => {
    mockGenerate.current = vi.fn().mockResolvedValue({ text: "见 [[c:c1]]", model: "m" });
    render(<ReportView />);
    fireEvent.click(screen.getByRole("button", { name: /generate report/i }));
    await waitFor(() => expect(screen.getByTestId("report-body")).toBeInTheDocument());

    fireEvent.click(screen.getByTestId("cite-chip"));
    const wb = mockWb.current as { dispatch: { setView: ReturnType<typeof vi.fn>; selectByCanvasClick: ReturnType<typeof vi.fn> } };
    expect(wb.dispatch.setView).toHaveBeenCalledWith("graph");
    expect(wb.dispatch.selectByCanvasClick).toHaveBeenCalled();
  });

  it("surfaces backend errors honestly", async () => {
    mockGenerate.current = vi.fn().mockRejectedValue(new Error("LLM is not configured"));
    render(<ReportView />);
    fireEvent.click(screen.getByRole("button", { name: /generate report/i }));
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(screen.getByRole("alert").textContent).toContain("LLM is not configured");
  });

  it("sends figure source packets and expands [[fig:...]] in the generated report", async () => {
    mockFigureArtifacts.groups = [
      {
        artifact_type: "figure",
        items: [{ artifact_id: "coef_plot", path: "figures/coef_plot.png", artifact_type: "figure" }],
      },
    ];
    mockFigureContext.mockResolvedValue({
      figure: { artifact_id: "coef_plot", path: "figures/coef_plot.png", chart_type: "coefficient plot", sha256: null },
      source: { artifact_id: "ols_1", kind: "model", preview_json: '{"estimate":2.0}', sha256: null, path: "model_results/ols_1.json", preview_truncated: false },
    });
    mockGenerate.current = vi.fn().mockResolvedValue({
      text: "# Results\n\n[[fig:coef_plot]]",
      model: "m",
    });
    render(<ReportView projectRoot="/tmp/projA" />);

    await waitFor(() => expect(mockFigureContext).toHaveBeenCalledWith("/tmp/projA", "run_c", "coef_plot"));
    fireEvent.click(screen.getByRole("button", { name: /generate report/i }));
    await waitFor(() => expect(screen.getByTestId("report-figure-coef_plot")).toBeInTheDocument());

    const sent = mockGenerate.current.mock.calls[0][0] as {
      facts: Array<{ field: string; value: unknown }>;
      figures: Array<{ artifact_id: string; source: unknown }>;
    };
    expect(sent.figures).toHaveLength(1);
    expect(sent.figures[0].artifact_id).toBe("coef_plot");
    expect(sent.figures[0].source).toEqual({
      artifact_id: "ols_1",
      kind: "model",
      preview_json: '{"estimate":2.0}',
      sha256: null,
      path: "model_results/ols_1.json",
      preview_truncated: false,
    });
    expect(sent.facts.some((fact: { field: string; value: unknown }) =>
      fact.field === "figure:coef_plot:source.estimate" && fact.value === 2,
    )).toBe(true);
    expect(screen.getByTestId("report-figure-coef_plot").getAttribute("src")).toContain("coef_plot");
  });

  it("surfaces a backend contract error when the model omits a marker", async () => {
    mockFigureArtifacts.groups = [
      {
        artifact_type: "figure",
        items: [{ artifact_id: "coef_plot", path: "figures/coef_plot.png", artifact_type: "figure" }],
      },
    ];
    mockFigureContext.mockResolvedValue({
      figure: { artifact_id: "coef_plot", path: "figures/coef_plot.png", chart_type: "coefficient plot", sha256: null },
      source: null,
    });
    mockGenerate.current = vi.fn().mockRejectedValue(
      new Error("LLM_RESPONSE_CONTRACT_INVALID"),
    );
    render(<ReportView projectRoot="/tmp/projA" />);

    await waitFor(() =>
      expect(screen.getByRole("button", { name: /generate report/i })).toBeEnabled(),
    );
    fireEvent.click(screen.getByRole("button", { name: /generate report/i }));
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(screen.getByRole("alert").textContent).toContain("LLM_RESPONSE_CONTRACT_INVALID");
    expect(screen.queryByTestId("report-body")).not.toBeInTheDocument();
  });

  it("without an active run, asks the user to pick one", () => {
    mockForest.current = null;
    render(<ReportView />);
    expect(screen.getByText(/pick a run/i)).toBeInTheDocument();
  });

  it("lets the user choose which run's report facts are in view", () => {
    render(<ReportView />);

    expect(screen.getByTestId("report-view-run-picker")).toHaveClass(
      "wb-run-version-picker",
    );
    expect(screen.getByTestId("report-view-run-picker")).toHaveTextContent(
      "Versions:",
    );
    expect(screen.getByRole("button", { name: "Show report for run run_a" })).toHaveClass(
      "wb-run-version-picker__button",
    );
    fireEvent.click(screen.getByRole("button", { name: "Show report for run run_a" }));

    const forest = mockForest.current as { setActiveRunId: ReturnType<typeof vi.fn> };
    expect(forest.setActiveRunId).toHaveBeenCalledWith("run_a");
  });

  it("keeps the compact Run identifier visible for a single-run report", () => {
    const seed = seedForest();
    mockForest.current = {
      forest: { ...seed.forest, heads: [{ runId: "only-run", createdAt: "2026-07-30T00:00:00Z" }] },
      activeRunId: "only-run",
      setActiveRunId: vi.fn(),
    };

    render(<ReportView />);

    expect(screen.getByTestId("report-view-run-picker")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Show report for run only-run" })).toHaveClass(
      "wb-run-version-picker__button",
    );
  });

  it("keeps persisted report history scoped to the selected run", async () => {
    mockFetchAiReports.mockResolvedValue([
      {
        id: "report-run-a",
        generatedAt: "2026-07-30T10:00:00Z",
        model: "model-a",
        instruction: "Run A only",
        text: "Run A report",
        scope: { run_id: "run_a", node_count: 1 },
        facts: [],
        excluded_fact_ids: [],
        figures: [],
      },
      {
        id: "report-run-c",
        generatedAt: "2026-07-30T11:00:00Z",
        model: "model-c",
        instruction: "Run C only",
        text: "Run C report",
        scope: { run_id: "run_c", node_count: 1 },
        facts: [],
        excluded_fact_ids: [],
        figures: [],
      },
    ]);

    render(<ReportView projectRoot="/tmp/run-scoped-report-history" />);

    expect(await screen.findByText("Run C report")).toBeInTheDocument();
    expect(screen.getByText("Run C only")).toBeInTheDocument();
    expect(screen.queryByText("Run A report")).not.toBeInTheDocument();
    expect(screen.queryByText("Run A only")).not.toBeInTheDocument();
  });

  it("does not show a completed report from a run that is no longer active", async () => {
    let resolveGenerate: ((value: { text: string; model: string }) => void) | undefined;
    mockGenerate.current = vi.fn().mockReturnValue(new Promise((resolve) => {
      resolveGenerate = resolve;
    }));
    const setActiveRunId = vi.fn();
    mockForest.current = {
      ...(mockForest.current as object),
      activeRunId: "run_c",
      setActiveRunId,
    };

    const view = render(<ReportView projectRoot="/tmp/run-switch-race" />);
    fireEvent.click(await screen.findByRole("button", { name: /generate report/i }));

    mockForest.current = {
      ...(mockForest.current as object),
      activeRunId: "run_a",
      setActiveRunId,
    };
    view.rerender(<ReportView projectRoot="/tmp/run-switch-race" />);
    resolveGenerate?.({ text: "Run C async report", model: "model-c" });

    await waitFor(() => expect(mockSaveAiReport).toHaveBeenCalledTimes(1));
    expect(mockSaveAiReport.mock.calls[0][0]).toMatchObject({ runId: "run_c" });
    expect(screen.queryByText("Run C async report")).not.toBeInTheDocument();
    expect(screen.queryByTestId("report-body")).not.toBeInTheDocument();
  });

  it("does not generate a report when the run figure inventory cannot load", async () => {
    mockFigureArtifactsError.current = new Error("artifact inventory unavailable");
    render(<ReportView projectRoot="/tmp/projA" />);

    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(screen.getByRole("alert").textContent).toContain("figure inventory");
    expect(screen.getByRole("button", { name: /generate report/i })).toBeDisabled();
    expect(mockGenerate.current).not.toHaveBeenCalled();
  });
});

describe("ReportView curation & history (C-3)", () => {
  beforeEach(() => {
    window.localStorage.clear();
    const seed = seedForest();
    mockForest.current = { forest: seed.forest, activeRunId: "run_c", setActiveRunId: vi.fn() };
    mockWb.current = {
      state: {},
      dispatch: { setView: vi.fn(), selectByCanvasClick: vi.fn() },
    };
    mockGenerate.current = vi.fn().mockResolvedValue({ text: "ok [[c:c1]]", model: "m" });
    mockFigureArtifacts.groups = [];
    mockFigureArtifactsError.current = null;
    mockFigureContext.mockReset();
  });

  it("unticking a fact excludes it from generation and discloses the exclusion", async () => {
    render(<ReportView projectRoot="/tmp/projA" />);
    const checkboxes = screen.getAllByRole("checkbox");
    fireEvent.click(checkboxes[0]); // exclude the first fact

    expect(screen.getByTestId("report-provenance").textContent).toContain(
      "excluded by user",
    );

    await waitFor(() =>
      expect(screen.getByRole("button", { name: /generate report/i })).toBeEnabled(),
    );
    fireEvent.click(screen.getByRole("button", { name: /generate report/i }));
    await waitFor(() => expect(screen.getByTestId("report-body")).toBeInTheDocument());

    const sent = mockGenerate.current.mock.calls[0][0] as {
      facts: Array<{ id: string }>;
    };
    // one fewer fact was sent than exists in the table
    expect(sent.facts.length).toBe(1);
    // provenance of the generated report keeps the disclosure
    expect(screen.getByTestId("report-provenance").textContent).toContain(
      "facts were excluded",
    );
  });

  it("there is no UI to edit a fact's value (omit-only curation)", () => {
    render(<ReportView projectRoot="/tmp/projA" />);
    const preview = screen.getByTestId("report-fact-preview");
    // checkboxes only — no text inputs anywhere in the fact table
    expect(preview.querySelectorAll("input[type=text], textarea").length).toBe(0);
  });

  it("generated reports persist to history and reopen from it", async () => {
    render(<ReportView projectRoot="/tmp/projA" />);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /generate report/i })).toBeEnabled(),
    );
    fireEvent.click(screen.getByRole("button", { name: /generate report/i }));
    await waitFor(() => expect(screen.getByTestId("report-history")).toBeInTheDocument());

    // back to fact table, then reopen the historical report
    fireEvent.click(screen.getByRole("button", { name: /new report/i }));
    expect(screen.getByTestId("report-fact-preview")).toBeInTheDocument();
    const historyLinks = screen
      .getByTestId("report-history")
      .querySelectorAll("button");
    fireEvent.click(historyLinks[0]);
    expect(screen.getByTestId("report-body")).toBeInTheDocument();

    // history survives a remount (localStorage)
    const again = render(<ReportView projectRoot="/tmp/projA" />);
    expect(again.getAllByTestId("report-history").length).toBeGreaterThan(0);
  });

  it("deleting a history record removes it", async () => {
    render(<ReportView projectRoot="/tmp/projB" />);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /generate report/i })).toBeEnabled(),
    );
    fireEvent.click(screen.getByRole("button", { name: /generate report/i }));
    await waitFor(() => expect(screen.getByTestId("report-history")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /delete report/i }));
    expect(screen.queryByTestId("report-history")).toBeNull();
  });
});
