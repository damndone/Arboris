import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { makeOwnerResolutionSeedFixture } from "../lineage/api/nodeOperationContext";
import { loadAiActivity } from "../aiActivity/aiActivityLog";
import { ReportReviewPanel } from "./ReportReviewPanel";
import { ReportViewContent } from "./ReportView";
import { ReportWorkspaceProvider } from "./ReportWorkspaceContext";

const mockForest = vi.hoisted(() => ({ current: null as unknown }));
const mockWb = vi.hoisted(() => ({ current: null as unknown }));
const mockGenerate = vi.hoisted(() => ({
  current: vi.fn() as ReturnType<typeof vi.fn>,
}));
const mockExportResultTable = vi.hoisted(() => ({
  current: vi.fn() as ReturnType<typeof vi.fn>,
}));
const mockExportReport = vi.hoisted(() => ({
  current: vi.fn() as ReturnType<typeof vi.fn>,
}));
const mockSaveAiReport = vi.hoisted(() => vi.fn());
const mockFetchAiReports = vi.hoisted(() => vi.fn());
const mockRunDetail = vi.hoisted(() => ({ current: vi.fn() }));
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
    exportReport: (...args: unknown[]) => mockExportReport.current(...args),
    exportResultTable: (...args: unknown[]) => mockExportResultTable.current(...args),
    saveAiReport: (...args: unknown[]) => mockSaveAiReport(...args),
    fetchAiReports: (...args: unknown[]) => mockFetchAiReports(...args),
  };
});
vi.mock("../api", async (importOriginal) => {
  const original = await importOriginal<typeof import("../api")>();
  return {
    ...original,
    fetchRunDetail: (...args: unknown[]) => mockRunDetail.current(...args),
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

// The production ReportView is center-only after Task 2. This test surface
// mounts the future review host beside it so the existing lifecycle assertions
// continue to exercise the shared provider rather than duplicate state.
function ReportView({ projectRoot }: { projectRoot?: string }) {
  return (
    <ReportWorkspaceProvider projectRoot={projectRoot}>
      <ReportViewContent />
      <ReportReviewPanel />
    </ReportWorkspaceProvider>
  );
}

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
    window.localStorage.clear();
    const seed = seedForest();
    mockForest.current = { forest: seed.forest, activeRunId: "run_c", setActiveRunId: vi.fn() };
    mockWb.current = {
      state: {},
      dispatch: { setView: vi.fn(), selectByCanvasClick: vi.fn() },
    };
    mockGenerate.current = vi.fn();
    mockExportResultTable.current.mockReset();
    mockExportResultTable.current.mockResolvedValue(new Blob(["xlsx"]));
    mockExportReport.current.mockReset();
    mockExportReport.current.mockResolvedValue(new Blob(["report"]));
    mockSaveAiReport.mockReset();
    mockFetchAiReports.mockReset();
    mockFetchAiReports.mockResolvedValue([]);
    mockRunDetail.current = vi.fn().mockResolvedValue({
      model_results: [],
      post_estimation_results: [],
      prediction_evidence: null,
    });
    mockFigureArtifacts.groups = [];
    mockFigureArtifactsError.current = null;
    mockFigureContext.mockReset();
    mockArtifactJson.mockReset();
  });

  it("shows the deterministic fact table before any AI call", () => {
    render(<ReportView />);
    expect(screen.getByTestId("report-fact-preview")).toBeInTheDocument();
    expect(screen.getByText("Covariance")).toBeInTheDocument();
    expect(screen.queryByText("param:covariance")).not.toBeInTheDocument();
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

    expect(await screen.findByText("Selected ARMA specification")).toBeInTheDocument();
    expect(screen.getByText("Validation RMSE")).toBeInTheDocument();
    expect(screen.getByText("Analysis transform")).toBeInTheDocument();
    expect(screen.getByText("Analysis-view observations")).toBeInTheDocument();
    expect(screen.queryByText("ts:arma:selected_candidate")).not.toBeInTheDocument();
    expect(screen.getByText("arma-p1-q1-n")).toBeInTheDocument();
  });

  it("projects persisted model results into deterministic regression evidence", async () => {
    mockRunDetail.current = vi.fn().mockResolvedValue({
      model_results: [
        {
          model_id: "ols_1",
          model_type: "Baseline",
          nobs: 100,
          coefficients: {
            x: {
              estimate: 1.25,
              std_error: 0.2,
              p_value: 0.04,
              ci_lower: 0.8,
              ci_upper: 1.7,
              source_id: "model_results.ols_1.coefficients.x",
            },
          },
        },
      ],
      post_estimation_results: [],
      prediction_evidence: null,
    });

    render(<ReportView projectRoot="/tmp/projA" />);

    expect(await screen.findByTestId("regression-evidence")).toBeInTheDocument();
    expect(screen.getByText("Baseline (ols_1)")).toBeInTheDocument();
    expect(screen.getByText("1.25 **")).toBeInTheDocument();
    expect(screen.getByText("source: model_results.ols_1.coefficients.x")).toBeInTheDocument();
    expect(screen.queryByTestId("model-family-evidence")).not.toBeInTheDocument();
  });

  it("shows typed family evidence from the serialized RunDetail and artifact packets", async () => {
    mockRunDetail.current = vi.fn().mockResolvedValue({
      model_results: [{
        contract: "workbench.ordinal_logit.result.v1",
        schema_version: 1,
        model_id: "ordinal_logit_1",
        model_type: "ordinal_logit",
        outcome_levels: ["low", "middle", "high"],
        coefficients: {
          education: {
            estimate: 0.76,
            std_error: 0.2,
            p_value: 0.02,
            ci_lower: 0.37,
            ci_upper: 1.15,
          },
        },
        odds_ratios: {
          education: { odds_ratio: 2.15, ci_lower: 1.4, ci_upper: 3.3 },
        },
        marginal_effects: [{
          variable: "education",
          average_effect_by_category: { low: -0.12, middle: 0.03, high: 0.09 },
        }],
        predicted_probabilities: [{
          row: 0,
          probabilities: { low: 0.2, middle: 0.5, high: 0.3 },
        }],
        diagnostic_artifacts: ["diagnostics_ordinal_logit_1"],
      }],
      post_estimation_results: [],
      prediction_evidence: null,
    });
    mockFigureArtifacts.groups = [{
      artifact_type: "model_diagnostic",
      items: [{
        artifact_id: "diagnostics_ordinal_logit_1",
        path: "model_results/diagnostics_ordinal_logit_1.json",
        artifact_type: "model_diagnostic",
      }],
    }];
    mockArtifactJson.mockImplementation((_root, _run, artifactId) => {
      if (artifactId === "diagnostics_ordinal_logit_1") {
        return Promise.resolve({
          contract: "workbench.ordinal_logit.diagnostics.v1",
          parallel_lines: {
            status: "computed",
            method: "cumulative_logit_slope_range",
            slope_ranges: { education: 0.31 },
            comparisons: [{ threshold: 1, coefficients: { education: 0.9 } }],
          },
        });
      }
      return Promise.resolve(undefined);
    });

    render(<ReportView projectRoot="/tmp/projA" />);

    const familyEvidence = await screen.findByTestId("family-evidence-ordinal_logit_1");
    expect(familyEvidence).toHaveTextContent("2.15");
    expect(familyEvidence).toHaveTextContent(/parallel-lines/i);
    expect(screen.getByTestId("regression-evidence")).toHaveTextContent("0.76");
  });

  it("generate renders prose with verified chips and flags unknown ids", async () => {
    mockGenerate.current = vi.fn().mockResolvedValue({
      text: "R² 良好 [[c:c2]],而这个引用不存在 [[c:c99]]。",
      model: "deepseek-v4-flash",
    });
    render(<ReportView />);
    fireEvent.click(await screen.findByRole("button", { name: /generate report/i }));

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
    expect(mockSaveAiReport.mock.calls[0][0].record.context_fingerprints)
      .toEqual(expect.arrayContaining([expect.stringMatching(/^report-evidence-v1:/)]));
  });

  it("does not let late durable history replace a newly generated draft", async () => {
    let resolveHistory: ((records: unknown[]) => void) | undefined;
    mockFetchAiReports.mockReturnValue(new Promise((resolve) => {
      resolveHistory = resolve;
    }));
    mockGenerate.current = vi.fn().mockResolvedValue({ text: "New draft [[c:c1]]", model: "m" });
    render(<ReportView projectRoot="/tmp/projA" />);

    await waitFor(() => expect(mockFetchAiReports).toHaveBeenCalledTimes(1));
    fireEvent.click(await screen.findByRole("button", { name: /generate report/i }));
    await waitFor(() => expect(screen.getByTestId("report-body")).toBeInTheDocument());
    const revisionInput = screen.getByRole("textbox", { name: "Report revision instruction" });
    fireEvent.change(revisionInput, { target: { value: "Keep this draft visible" } });

    resolveHistory?.([{
      id: "old-durable",
      generatedAt: "2026-07-30T10:00:00Z",
      instruction: "old",
      text: "Old durable report",
      scope: { run_id: "run_c", node_count: 1, node_keys: [] },
      facts: [],
      excluded_fact_ids: [],
    }]);
    await waitFor(() => expect(screen.getByTestId("report-body")).toHaveTextContent("New draft"));
    expect(screen.getByTestId("report-body")).not.toHaveTextContent("Old durable report");
    expect(revisionInput).toHaveValue("Keep this draft visible");
  });

  it("keeps report export actions visible and reserves More formats for document formats", async () => {
    mockGenerate.current = vi.fn().mockResolvedValue({ text: "Result [[c:c1]]", model: "m" });
    render(<ReportView projectRoot="/tmp/projA" />);

    expect(screen.getByRole("button", { name: "Export report" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Export result table" })).toBeDisabled();

    fireEvent.click(await screen.findByRole("button", { name: /generate report/i }));
    await waitFor(() => expect(screen.getByTestId("report-body")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Export report" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Export result table" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "More formats" }));
    expect(screen.queryByRole("menuitem", { name: "Export result table" })).not.toBeInTheDocument();
    fireEvent.mouseDown(document.body);
    expect(screen.queryByRole("menu", { name: "More report formats" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Export result table" }));
    await waitFor(() => expect(mockExportResultTable.current).toHaveBeenCalledWith({
      projectRoot: "/tmp/projA",
      runId: "run_c",
      sections: [],
    }));
  });

  it("sends report export through the download client instead of a silent print call", async () => {
    mockGenerate.current = vi.fn().mockResolvedValue({ text: "Result [[c:c1]]", model: "m" });
    const printSpy = vi.spyOn(window, "print").mockImplementation(() => undefined);
    render(<ReportView projectRoot="/tmp/projA" />);

    fireEvent.click(await screen.findByRole("button", { name: /generate report/i }));
    await waitFor(() => expect(screen.getByTestId("report-body")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Export report" }));

    await waitFor(() => expect(mockExportReport.current).toHaveBeenCalledWith(expect.objectContaining({
      projectRoot: "/tmp/projA",
      runId: "run_c",
      format: "pdf-print",
    })));
    expect(printSpy).not.toHaveBeenCalled();
    printSpy.mockRestore();
  });

  it("explains scope separately from source regression evidence", () => {
    render(<ReportView />);

    expect(screen.getByTestId("report-scope-summary")).toHaveTextContent("What this report covers");
    expect(screen.getByTestId("report-scope-summary")).toHaveTextContent("does not change Workbench data");
    expect(screen.getByTestId("report-scope-divider")).toBeInTheDocument();
    expect(screen.getByTestId("report-scope-divider").compareDocumentPosition(screen.getByTestId("report-evidence-divider")) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("allows prose-only report revisions while preserving the source evidence snapshot", async () => {
    mockGenerate.current = vi.fn().mockResolvedValue({ text: "Generated [[c:c1]]", model: "m" });
    render(<ReportView projectRoot="/tmp/projA" />);
    fireEvent.click(await screen.findByRole("button", { name: /generate report/i }));
    await waitFor(() => expect(screen.getByTestId("report-body")).toBeInTheDocument());
    const originalRecord = mockSaveAiReport.mock.calls[0][0].record as { id: string };

    fireEvent.click(screen.getByRole("button", { name: "Edit report" }));
    const editor = screen.getByRole("textbox", { name: "Report editor" });
    fireEvent.change(editor, { target: { value: "# Edited prose\nNo result values changed." } });
    expect(screen.getByRole("button", { name: "Save revision" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reset to generated draft" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Save revision" }));

    await waitFor(() => expect(mockSaveAiReport).toHaveBeenCalledTimes(2));
    const savedRevision = mockSaveAiReport.mock.calls[1][0].record as {
      text: string;
      scope: { run_id: string };
      facts: Array<{ id: string; value: unknown }>;
      revision?: { source: { source_record_id: string; source_run_id: string; facts: Array<{ id: string; value: unknown }> } };
    };
    expect(savedRevision.text).toBe("# Edited prose\nNo result values changed.");
    expect(savedRevision.scope.run_id).toBe("run_c");
    expect(savedRevision.facts).toEqual(expect.arrayContaining([
      expect.objectContaining({ id: "c1", value: "HC1" }),
    ]));
    expect(savedRevision.revision?.source.source_record_id).toBe(originalRecord.id);
    expect(savedRevision.revision?.source.source_run_id).toBe("run_c");
    expect(savedRevision.revision?.source.facts).toEqual(savedRevision.facts);
    expect(screen.getByTestId("report-body")).toHaveTextContent("Edited prose");

    fireEvent.click(screen.getByRole("button", { name: "Edit report" }));
    expect(screen.getByTestId("report-readonly-evidence")).toBeInTheDocument();
    expect(screen.getByTestId("report-readonly-evidence").querySelectorAll("input, textarea")).toHaveLength(0);
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
    render(<ReportView projectRoot="/tmp/projA" />);
    fireEvent.click(await screen.findByRole("button", { name: /generate report/i }));
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(screen.getByRole("alert").textContent).toContain("LLM is not configured");
    expect(loadAiActivity("/tmp/projA")).toEqual([
      expect.objectContaining({
        kind: "report_generate",
        status: "error",
        error: "LLM is not configured",
      }),
    ]);
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

  it("sends only selected figures while saving the complete figure provenance", async () => {
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
      text: "# Results\n\nNo figure selected.",
      model: "m",
    });
    render(<ReportView projectRoot="/tmp/projA" />);

    await waitFor(() => expect(mockFigureContext).toHaveBeenCalledWith("/tmp/projA", "run_c", "coef_plot"));
    fireEvent.click(screen.getByRole("button", { name: "Choose figures" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Include figure coef_plot" }));
    expect(screen.getByTestId("report-figure-selection")).toHaveTextContent("Inventory: 1 in provenance · Next writer packet: 0 selected");

    fireEvent.click(screen.getByRole("button", { name: /generate report/i }));
    await waitFor(() => expect(screen.getByTestId("report-body")).toBeInTheDocument());

    const sent = mockGenerate.current.mock.calls[0][0] as {
      facts: Array<{ node_key: string }>;
      figures: Array<{ artifact_id: string }>;
    };
    expect(sent.figures).toEqual([]);
    expect(sent.facts.some((fact) => fact.node_key === "figure:coef_plot")).toBe(false);
    const saved = mockSaveAiReport.mock.calls[0][0].record as {
      figures: Array<{ artifact_id: string }>;
      excluded_figure_ids: string[];
    };
    expect(saved.figures.map((figure) => figure.artifact_id)).toEqual(["coef_plot"]);
    expect(saved.excluded_figure_ids).toEqual(["coef_plot"]);
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

  it("starts with a generic report prompt and separates regression from report evidence", () => {
    render(<ReportView projectRoot="/tmp/projA" />);

    const reportView = screen.getByTestId("report-view");
    expect(reportView.style.boxSizing).toBe("border-box");
    expect(reportView.style.width).toBe("100%");
    expect(reportView.style.minWidth).toBe("0");
    const instruction = screen.getByRole("textbox", { name: "Report instruction" });
    expect(instruction).toHaveValue("");
    expect(instruction).toHaveAttribute(
      "placeholder",
      "Tell the agent what you want to explore or change…",
    );
    expect(screen.getByTestId("report-evidence-divider")).toHaveTextContent(
      "Report evidence (what the AI may reference)",
    );
    expect(screen.getByTestId("report-evidence-divider")).toHaveTextContent(
      "Regression evidence above is source output; this section is the citable report context.",
    );
  });

  it("opens the shared report review with a prose-only revision prompt after generation", async () => {
    mockGenerate.current = vi.fn().mockResolvedValue({
      text: "# Draft report\n\nResult [[c:c1]]",
      model: "m",
    });
    render(<ReportView projectRoot="/tmp/projA" />);

    await waitFor(() => expect(screen.getByRole("button", { name: /generate report/i })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: /generate report/i }));
    await waitFor(() => expect(mockGenerate.current).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.getByTestId("report-review-panel")).toBeInTheDocument());
    expect(screen.getByRole("textbox", { name: "Report revision instruction" }))
      .toHaveAttribute("placeholder", "Tell the agent what you want to explore or change…");
    expect(screen.getByText(/source facts, results, and lineage remain read-only/i))
      .toBeInTheDocument();
  });

  it("sends a revision request with the current draft while preserving the evidence packet", async () => {
    mockGenerate.current = vi.fn()
      .mockResolvedValueOnce({ text: "# Original\n\nResult [[c:c1]]", model: "m" })
      .mockResolvedValueOnce({ text: "# Revised\n\nResult [[c:c1]]", model: "m" });
    render(<ReportView projectRoot="/tmp/projA" />);

    await waitFor(() => expect(screen.getByRole("button", { name: /generate report/i })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: /generate report/i }));
    await waitFor(() => expect(screen.getByTestId("report-review-panel")).toBeInTheDocument());

    // Changing the live curation after generation must not rewrite the
    // immutable evidence packet carried by a prose-only revision.
    fireEvent.click(screen.getByRole("checkbox", { name: "Include fact c1" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Report revision instruction" }), {
      target: { value: "Explain the limitation more clearly" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Revise draft" }));
    await waitFor(() => expect(mockGenerate.current).toHaveBeenCalledTimes(2));

    const revisionRequest = mockGenerate.current.mock.calls[1][0] as {
      instruction: string;
      facts: Array<{ id: string; value: unknown }>;
      excludedFactIds: string[];
    };
    expect(revisionRequest.instruction).toContain("Explain the limitation more clearly");
    expect(revisionRequest.instruction).toContain("# Original");
    expect(revisionRequest.facts).toEqual(expect.arrayContaining([
      expect.objectContaining({ id: "c1", value: "HC1" }),
    ]));
    expect(revisionRequest.excludedFactIds).not.toContain("c1");

    await waitFor(() => expect(mockSaveAiReport).toHaveBeenCalledTimes(2));
    const original = mockSaveAiReport.mock.calls[0][0].record as {
      id: string;
      generatedText?: string;
      facts: unknown[];
      revision?: { revision_id: string; revision_number: number; source: { source_record_id: string } };
    };
    const revised = mockSaveAiReport.mock.calls[1][0].record as {
      generatedText?: string;
      facts: unknown[];
      revision?: {
        parent_revision_id?: string;
        revision_number: number;
        source: { source_record_id: string };
      };
    };
    expect(revised.revision?.source.source_record_id).toBe(original.id);
    expect(revised.revision?.parent_revision_id).toBe(original.revision?.revision_id);
    expect(revised.revision?.revision_number).toBe((original.revision?.revision_number ?? 0) + 1);
    expect(revised.generatedText).toBe(original.generatedText);
    expect(revised.facts).toEqual(original.facts);
  });

  it("keeps the revision instruction after a failed revision so it can be retried", async () => {
    mockGenerate.current = vi.fn()
      .mockResolvedValueOnce({ text: "# Original\n\nResult [[c:c1]]", model: "m" })
      .mockRejectedValueOnce(new Error("temporary writer failure"));
    render(<ReportView projectRoot="/tmp/projA" />);

    await waitFor(() => expect(screen.getByRole("button", { name: /generate report/i })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: /generate report/i }));
    await waitFor(() => expect(screen.getByTestId("report-review-panel")).toBeInTheDocument());

    const revisionInput = screen.getByRole("textbox", { name: "Report revision instruction" });
    fireEvent.change(revisionInput, { target: { value: "Clarify the data limitation" } });
    fireEvent.click(screen.getByRole("button", { name: "Revise draft" }));

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("temporary writer failure"));
    expect(revisionInput).toHaveValue("Clarify the data limitation");
    expect(screen.getByTestId("report-body")).toHaveTextContent("Original");
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
    mockFetchAiReports.mockReset();
    mockFetchAiReports.mockResolvedValue([]);
    mockRunDetail.current = vi.fn().mockResolvedValue({
      model_results: [],
      post_estimation_results: [],
      prediction_evidence: null,
    });
  });

  it("groups evidence rows and keeps raw fields behind the evidence details disclosure", () => {
    render(<ReportView projectRoot="/tmp/projA" />);

    expect(screen.getByText("Model and estimation")).toBeInTheDocument();
    expect(screen.getByText("Model and estimation").closest("details")).not.toHaveAttribute("open");
    expect(screen.getByText("Covariance")).toBeInTheDocument();
    expect(screen.queryByText("param:covariance")).not.toBeInTheDocument();
    const details = screen.getByText("Evidence details for fact c1").closest("details");
    expect(details).toBeInTheDocument();
    expect(details).toHaveTextContent("field: param:covariance");
  });

  it("unticking a fact excludes it from generation and discloses the exclusion", async () => {
    render(<ReportView projectRoot="/tmp/projA" />);
    fireEvent.click(screen.getByRole("checkbox", { name: "Include fact c1" }));

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
      reportStandard: string;
      capabilityManifest: Array<{ provider_id: string }>;
    };
    // one fewer fact was sent than exists in the table
    expect(sent.facts.length).toBe(1);
    expect(sent.reportStandard).toBe("journal_full_v1");
    expect(sent.capabilityManifest[0].provider_id).toBe("evidence.estimation.v1");
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
    fireEvent.click(screen.getByRole("checkbox", { name: "Include fact c1" }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /generate report/i })).toBeEnabled(),
    );
    fireEvent.click(screen.getByRole("button", { name: /generate report/i }));
    await waitFor(() => expect(screen.getByTestId("report-history")).toBeInTheDocument());

    // back to fact table, then reopen the historical report
    fireEvent.click(screen.getByRole("button", { name: /new report/i }));
    expect(screen.getByTestId("report-fact-preview")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Include fact c1" })).toBeChecked();
    const historyLinks = screen
      .getByTestId("report-history")
      .querySelectorAll("button");
    fireEvent.click(historyLinks[0]);
    expect(screen.getByTestId("report-body")).toBeInTheDocument();
    expect(screen.getByTestId("report-provenance").textContent).toMatch(/next writer packet: 1 of \d+ selected/);
    expect(screen.getByTestId("report-provenance").textContent).toContain("facts were excluded");

    // history survives a remount (localStorage)
    const again = render(<ReportView projectRoot="/tmp/projA" />);
    expect(again.getAllByTestId("report-history").length).toBeGreaterThan(0);
  });

  it("starts a new report with all facts included", async () => {
    render(<ReportView projectRoot="/tmp/projA" />);
    fireEvent.click(screen.getByRole("checkbox", { name: "Include fact c1" }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /generate report/i })).toBeEnabled(),
    );
    fireEvent.click(screen.getByRole("button", { name: /generate report/i }));
    await waitFor(() => expect(screen.getByTestId("report-body")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: /new report/i }));
    expect(screen.getByRole("checkbox", { name: "Include fact c1" })).toBeChecked();
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
