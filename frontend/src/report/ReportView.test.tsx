import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { makeOwnerResolutionSeedFixture } from "../lineage/api/nodeOperationContext";
import { ReportView } from "./ReportView";

const mockForest = vi.hoisted(() => ({ current: null as unknown }));
const mockWb = vi.hoisted(() => ({ current: null as unknown }));
const mockGenerate = vi.hoisted(() => ({
  current: vi.fn() as ReturnType<typeof vi.fn>,
}));
const mockFigureArtifacts = vi.hoisted(() => ({ groups: [] as unknown[] }));
const mockFigureContext = vi.hoisted(() => vi.fn());
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
  };
});
vi.mock("../api", async (importOriginal) => {
  const original = await importOriginal<typeof import("../api")>();
  return {
    ...original,
    fetchRunArtifacts: () => mockFigureArtifactsError.current
      ? Promise.reject(mockFigureArtifactsError.current)
      : Promise.resolve(mockFigureArtifacts),
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
    mockFigureArtifacts.groups = [];
    mockFigureArtifactsError.current = null;
    mockFigureContext.mockReset();
  });

  it("shows the deterministic fact table before any AI call", () => {
    render(<ReportView />);
    expect(screen.getByTestId("report-fact-preview")).toBeInTheDocument();
    expect(screen.getByText("param:covariance")).toBeInTheDocument();
    expect(mockGenerate.current).not.toHaveBeenCalled();
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
