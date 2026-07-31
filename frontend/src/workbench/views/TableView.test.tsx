import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { LineageContext } from "../../lineage/LineageContext";
import type { LineageContextValue } from "../../lineage/LineageContext";
import { ForestContext } from "../ForestContext";
import { WorkbenchStateProvider } from "../WorkbenchStateProvider";
import type { GraphViewModel } from "../../lineage/api/graphViewTypes";
import type { ArtifactsResponse, RunDetail } from "../../api";
import { completePublicModelResult } from "../repeatedMeasures/__fixtures__/publicModelResults";
import { TableView } from "./TableView";

const mockDetail = vi.hoisted(() => ({ current: null as unknown }));
const mockArtifacts = vi.hoisted(() => ({ current: null as unknown }));
const figureCtxMock = vi.hoisted(() => vi.fn());
const figureAskMock = vi.hoisted(() => vi.fn());
const figureImageMock = vi.hoisted(() => vi.fn());
const llmConfigMock = vi.hoisted(() => vi.fn());
const artifactJsonMock = vi.hoisted(() => vi.fn());

vi.mock("./figureAi", () => ({
  fetchFigureAiContext: (...args: unknown[]) => figureCtxMock(...args),
  askAiAboutFigure: (...args: unknown[]) => figureAskMock(...args),
  figureAsDataUrl: (...args: unknown[]) => figureImageMock(...args),
}));
vi.mock("../../llm/llmApi", () => ({
  fetchLlmConfig: (...args: unknown[]) => llmConfigMock(...args),
}));
const detailCalls = vi.hoisted(() => ({ current: [] as unknown[][] }));
const artifactCalls = vi.hoisted(() => ({ current: [] as unknown[][] }));

vi.mock("../../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../api")>();
  return {
    ...actual,
    fetchRunDetail: (...args: unknown[]) => {
      detailCalls.current.push(args);
      return Promise.resolve(mockDetail.current as RunDetail);
    },
    fetchRunArtifacts: (...args: unknown[]) => {
      artifactCalls.current.push(args);
      return Promise.resolve((mockArtifacts.current ?? { groups: [] }) as ArtifactsResponse);
    },
    fetchArtifactJson: (...args: unknown[]) => artifactJsonMock(...args),
  };
});

function model(runId = "run-1"): GraphViewModel {
  return {
    schemaVersion: 1,
    runId,
    legacy: false,
    nodes: [],
    edges: [],
    stats: {} as GraphViewModel["stats"],
  };
}

function renderTable(
  m: GraphViewModel = model(),
  options: { initialPath?: string; projectRoot?: string } = {},
) {
  const ctx: LineageContextValue = {
    model: m,
    selectedKey: null,
    select: () => {},
  };
  return render(
    <MemoryRouter
      initialEntries={[
        options.initialPath ?? "/runs/run-1?project_root=/tmp/demo",
      ]}
    >
      <LineageContext.Provider value={ctx}>
        <TableView projectRoot={options.projectRoot} />
      </LineageContext.Provider>
    </MemoryRouter>,
  );
}

const emptyDetail = { model_results: [], artifact_counts: {} } as unknown as RunDetail;

describe("TableView", () => {
  beforeEach(() => {
    mockDetail.current = emptyDetail;
    mockArtifacts.current = { groups: [] };
    detailCalls.current = [];
    artifactCalls.current = [];
    figureCtxMock.mockReset();
    figureAskMock.mockReset();
    figureImageMock.mockReset();
    llmConfigMock.mockReset();
    artifactJsonMock.mockReset();
    llmConfigMock.mockResolvedValue({ configured: true, supports_vision: false });
  });

  it("calls fetchRunDetail + fetchRunArtifacts with (projectRoot, runId) in that order", async () => {
    renderTable(model("run-1"));
    await waitFor(() => expect(detailCalls.current.length).toBeGreaterThan(0));
    await waitFor(() => expect(artifactCalls.current.length).toBeGreaterThan(0));
    // Both signatures are (projectRoot, runId) — guard against swapping.
    expect(detailCalls.current[0]).toEqual(["/tmp/demo", "run-1"]);
    expect(artifactCalls.current[0]).toEqual(["/tmp/demo", "run-1"]);
  });

  it("uses the shell projectRoot prop when the slug route has no project_root query", async () => {
    renderTable(model("run-slug"), {
      initialPath: "/p/encoded/graph?view=table",
      projectRoot: "/tmp/from-slug",
    });
    await waitFor(() => expect(detailCalls.current.length).toBeGreaterThan(0));
    expect(detailCalls.current[0]).toEqual(["/tmp/from-slug", "run-slug"]);
    expect(artifactCalls.current[0]).toEqual(["/tmp/from-slug", "run-slug"]);
  });

  it("renders a coefficient table from model_results", async () => {
    mockDetail.current = {
      model_results: [
        {
          model_id: "m1",
          model_type: "ols",
          r_squared: 0.42,
          r_squared_adj: 0.41,
          nobs: 100,
          coefficients: {
            education: { estimate: 0.08, std_error: 0.01, p_value: 0.001, p_value_display: "<0.001", ci_lower: 0.0604, ci_upper: 0.0996 },
            age: { estimate: 0.02, std_error: 0.005, p_value: 0.04, p_value_display: "0.04" },
          },
        },
      ],
      artifact_counts: {},
    } as unknown as RunDetail;

    renderTable();

    await waitFor(() => expect(screen.getByTestId("table-view-coefficients")).toBeTruthy());
    expect(screen.getByText("education")).toBeTruthy();
    expect(screen.getByText("age")).toBeTruthy();
    expect(screen.getByText("0.08")).toBeTruthy();
    expect(screen.getByRole("columnheader", { name: "95% CI" })).toBeTruthy();
    expect(screen.getByText("[0.0604, 0.0996]")).toBeTruthy();
    expect(screen.getByTestId("table-view-coefficient-scroll")).toHaveAttribute("tabindex", "0");
    // Stata `reg` prints Adj R-squared; a reader must not have to compute it.
    expect(screen.getByText(/adj\. R²=0\.41/)).toBeTruthy();
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });

  it("renders declared post-estimation results so the answer is on screen", async () => {
    mockDetail.current = {
      model_results: [],
      artifact_counts: {},
      post_estimation_results: [
        {
          artifact_id: "workflow_model_quadratic_stationary_point_abc",
          artifact_type: "post_estimation",
          operation_id: "model.quadratic_stationary_point",
          run_id: "run-source",
          model_run_id: "run-1",
          workflow_id: "wf-1",
          workflow_step_id: "stationary_point",
          result: {
            schema_version: "workbench.model.quadratic-stationary-point/v1",
            column: "experience",
            stationary_point: 211.59338521178753,
            observed_min: 1,
            observed_max: 25,
            stationary_point_within_observed_range: false,
            curvature: "maximum",
          },
        },
      ],
    } as unknown as RunDetail;

    renderTable(model("run-1"));

    await waitFor(() =>
      expect(screen.getByTestId("table-view-post-estimation")).toBeTruthy(),
    );
    expect(screen.getByText("Quadratic stationary point")).toBeTruthy();
    expect(screen.getByText("stationary point")).toBeTruthy();
    expect(screen.getByText("211.5934")).toBeTruthy();
    // The out-of-range flag is the difference between a number and a claim.
    expect(screen.getByText("stationary point within observed range")).toBeTruthy();
    expect(screen.getByText("no")).toBeTruthy();
    // Provenance, not decoration: it says which model the result describes.
    expect(screen.getByText(/stationary_point/)).toBeTruthy();
    // Internal schema tags are not reader-facing.
    expect(screen.queryByText(/workbench\.model\.quadratic/)).toBeNull();
  });

  it("omits the post-estimation section when a run declared none", async () => {
    mockDetail.current = {
      model_results: [],
      artifact_counts: {},
      post_estimation_results: [],
    } as unknown as RunDetail;

    renderTable(model("run-1"));
    await waitFor(() => expect(detailCalls.current.length).toBeGreaterThan(0));
    expect(screen.queryByTestId("table-view-post-estimation")).toBeNull();
  });

  it("renders the canonical LMM packet coefficient and diagnostic", async () => {
    mockDetail.current = {
      model_results: [completePublicModelResult()],
      artifact_counts: {},
    } as unknown as RunDetail;

    renderTable();

    await waitFor(() => expect(screen.getByTestId("table-view-coefficients")).toBeTruthy());
    expect(screen.getByText("group_time_interaction")).toBeTruthy();
    expect(screen.getByText("0.8")).toBeTruthy();
    expect(screen.getByTestId("table-view-lmm-diagnostics"))
      .toHaveTextContent("LMM_RANDOM_SLOPE_NEAR_ZERO");
  });

  it("renders every figure artifact as an <img> pointing at the artifact download URL", async () => {
    mockArtifacts.current = {
      groups: [
        {
          artifact_type: "figure",
          items: [
            { artifact_id: "correlation_heatmap", path: "figures/correlation_heatmap.png", artifact_type: "figure", step: "viz", sha256: "a" },
            { artifact_id: "qq_residuals", path: "figures/qq_residuals.png", artifact_type: "figure", step: "viz", sha256: "b" },
          ],
        },
      ],
    } as unknown as ArtifactsResponse;

    renderTable();

    await waitFor(() => expect(screen.getByTestId("table-view-figures")).toBeTruthy());
    const imgs = screen.getAllByRole("img");
    expect(imgs).toHaveLength(2);
    // src must hit the artifact endpoint with the right run + artifact id.
    expect(imgs[0].getAttribute("src")).toContain("correlation_heatmap");
    expect(imgs[0].getAttribute("src")).toContain("run-1");
    expect(imgs[0].getAttribute("src")).toContain("project_root");
    // G2: each figure exposes an "Ask AI about this figure" entry (numbers, not pixels).
    expect(screen.getByTestId("figure-ask-ai-button-correlation_heatmap")).toBeTruthy();
    // human-readable caption/alt
    expect(imgs[0].getAttribute("alt")).toContain("correlation_heatmap");

    fireEvent.contextMenu(imgs[0]);
    expect(screen.getByRole("menu", { name: "Chart actions" })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "Download chart" })).toHaveAttribute("download");

    fireEvent.pointerDown(document.body);
    expect(screen.queryByRole("menu", { name: "Chart actions" })).toBeNull();
  });

  it("renders ARMA-GARCH JSON chart artifacts in Table alongside static figures", async () => {
    mockArtifacts.current = {
      groups: [
        {
          artifact_type: "figure",
          items: Array.from({ length: 4 }, (_, index) => ({
            artifact_id: `eda_${index + 1}`,
            path: `figures/eda_${index + 1}.png`,
            artifact_type: "figure",
            step: "viz",
            sha256: String(index),
          })),
        },
        {
          artifact_type: "time_series_json",
          items: [
            {
              artifact_id: "ts.chart.series_transform",
              path: "artifacts/time_series/ts.chart.series_transform.json",
              artifact_type: "time_series_json",
              step: "time_series_diagnostics",
              sha256: "ts-series",
            },
          ],
        },
      ],
    } as unknown as ArtifactsResponse;
    artifactJsonMock.mockResolvedValue({
      payload: {
        rows: [
          { row_id: "source-row:0", time: "2020-01-01", source_value: 20, transformed_value: 0.1 },
          { row_id: "source-row:1", time: "2020-01-02", source_value: 21, transformed_value: 0.2 },
        ],
      },
    });

    renderTable();

    expect(await screen.findByText("Figures (4)")).toBeInTheDocument();
    expect(await screen.findByRole("img", { name: "Source series" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Transformed series (the modelled quantity)" }))
      .toBeInTheDocument();
    expect(screen.getByText(/1 chart artifacts loaded · 2 displayed panels/)).toBeInTheDocument();
  });

  it("renders grouped statistical exploration results as a readable table", async () => {
    mockArtifacts.current = {
      groups: [
        {
          artifact_type: "statistical_exploration",
          items: [
            {
              artifact_id: "statistical_exploration_years",
              path: "artifacts/statistical_exploration/statistical_exploration_years.json",
              artifact_type: "statistical_exploration",
              step: "statistical_exploration",
              sha256: "exploration-sha",
            },
          ],
        },
      ],
    } as unknown as ArtifactsResponse;
    artifactJsonMock.mockResolvedValue({
      spec: { operation: "summarize", options: { group_by: "year" } },
      result: {
        operation: "summarize",
        source_row_count: 4110,
        filtered_row_count: 4110,
        group_by: "year",
        groups: [
          {
            value: 1998,
            filtered_row_count: 685,
            variables: {
              bdsnew: { obs: 685, mean: 314738.1, std_dev: 120738.7, min: 101015, max: 531075 },
            },
          },
          {
            value: 2002,
            filtered_row_count: 685,
            variables: {
              bdsnew: { obs: 685, mean: 314738.1, std_dev: 120738.7, min: 101015, max: 531075 },
            },
          },
        ],
      },
    });

    renderTable();

    const table = await screen.findByTestId("table-view-statistical-exploration");
    expect(table).toHaveTextContent("Statistical exploration");
    expect(table).toHaveTextContent("1998");
    expect(table).toHaveTextContent("2002");
    expect(table).toHaveTextContent("bdsnew");
    expect(table).toHaveTextContent("314738.1");
    expect(artifactJsonMock).toHaveBeenCalledWith(
      "/tmp/demo",
      "run-1",
      "statistical_exploration_years",
    );
    expect(screen.getByTestId("table-view-statistical-exploration-scroll"))
      .toHaveAttribute("tabindex", "0");
  });

  it("renders a pooled correlation matrix with variable names, not a download hint", async () => {
    // `corr` returns `variables` as a list; the mapping/group branches skipped
    // it and the whole matrix reached the user as
    // "Result is available as the downloadable artifact."
    mockArtifacts.current = {
      groups: [
        {
          artifact_type: "statistical_exploration",
          items: [
            {
              artifact_id: "statistical_exploration_corr",
              path: "artifacts/statistical_exploration/statistical_exploration_corr.json",
              artifact_type: "statistical_exploration",
              step: "statistical_exploration",
              sha256: "corr-sha",
            },
          ],
        },
      ],
    } as unknown as ArtifactsResponse;
    artifactJsonMock.mockResolvedValue({
      spec: { operation: "corr" },
      result: {
        operation: "corr",
        source_row_count: 4110,
        filtered_row_count: 4110,
        correlation_n: 4055,
        variables: ["pfl", "pblack"],
        matrix: [
          [1.0, 0.3500236543],
          [0.3500236543, 1.0],
        ],
      },
    });

    renderTable();

    const table = await screen.findByTestId("table-view-statistical-exploration");
    expect(table).not.toHaveTextContent("Result is available as the downloadable artifact.");
    expect(table).toHaveTextContent("pfl");
    expect(table).toHaveTextContent("pblack");
    expect(table).toHaveTextContent("0.35");
  });

  it("lists non-figure artifacts with download links", async () => {
    mockArtifacts.current = {
      groups: [
        {
          artifact_type: "report",
          items: [
            { artifact_id: "html_report", path: "report.html", artifact_type: "report", step: "report", sha256: "c" },
          ],
        },
      ],
    } as unknown as ArtifactsResponse;

    renderTable();

    await waitFor(() => expect(screen.getByTestId("table-view-artifacts")).toBeTruthy());
    const link = screen.getByRole("link", { name: /html_report/ });
    expect(link.getAttribute("href")).toContain("html_report");
  });

  it("shows an empty state when the run has no results, figures, or artifacts", async () => {
    renderTable();
    await waitFor(() => expect(screen.getByTestId("table-view-empty")).toBeTruthy());
  });

  it("keeps the view=table switcher contract (data-view)", async () => {
    renderTable();
    expect(screen.getByTestId("view-table").getAttribute("data-view")).toBe("table");
    expect(screen.getByTestId("view-table")).toHaveStyle({
      padding: "12px 24px 24px",
    });
    await waitFor(() => expect(screen.getByTestId("table-view-empty")).toBeTruthy());
  });

  it("shows a run header with the (short) run id so results are attributable", async () => {
    renderTable(model("20260703_010101_000000_deadbeef"));
    const header = screen.getByTestId("table-view-run-header");
    expect(header.textContent).toContain("deadbeef");
    await waitFor(() => expect(screen.getByTestId("table-view-empty")).toBeTruthy());
  });

  it("follows the forest active head (not the URL run) for header + fetch", async () => {
    const ctx: LineageContextValue = { model: model("url-run"), selectedKey: null, select: () => {} };
    render(
      <MemoryRouter initialEntries={["/runs/url-run?project_root=/tmp/demo"]}>
        <ForestContext.Provider
          value={{
            forest: {} as never,
            activeRunId: "20260703_020202_000000_ac71ve00",
            setActiveRunId: () => {},
          }}
        >
          <LineageContext.Provider value={ctx}>
            <TableView />
          </LineageContext.Provider>
        </ForestContext.Provider>
      </MemoryRouter>,
    );
    // header + the data fetch both use the active head, not "url-run"
    expect(screen.getByTestId("table-view-run-header").textContent).toContain("ac71ve00");
    await waitFor(() => expect(detailCalls.current.length).toBeGreaterThan(0));
    expect(detailCalls.current[detailCalls.current.length - 1]).toEqual([
      "/tmp/demo",
      "20260703_020202_000000_ac71ve00",
    ]);
  });

  it("shows one active run at a time and lets the user choose another run", async () => {
    const setActiveRunId = vi.fn();
    mockDetail.current = {
      model_results: [
        {
          model_id: "active-model",
          model_type: "ols",
          coefficients: {},
        },
      ],
      artifact_counts: {},
    } as unknown as RunDetail;
    const ctx: LineageContextValue = { model: model("url-run"), selectedKey: null, select: () => {} };
    render(
      <MemoryRouter initialEntries={["/runs/url-run?project_root=/tmp/demo"]}>
        <ForestContext.Provider
          value={{
            forest: {
              heads: [
                { runId: "run_older", createdAt: "2026-07-29T00:00:00Z" },
                { runId: "run_current", createdAt: "2026-07-30T00:00:00Z" },
              ],
              nodes: [],
              edges: [],
              familyCount: 1,
              familyRunCount: 2,
            } as never,
            activeRunId: "run_current",
            setActiveRunId,
          }}
        >
          <LineageContext.Provider value={ctx}>
            <TableView />
          </LineageContext.Provider>
        </ForestContext.Provider>
      </MemoryRouter>,
    );

    await waitFor(() => expect(detailCalls.current.length).toBeGreaterThan(0));
    expect(screen.getAllByTestId("table-view-run-header")).toHaveLength(1);
    expect(screen.getByTestId("table-view-run-header")).toHaveTextContent("current");
    expect(detailCalls.current.map((args) => args[1])).toEqual(["run_current"]);
    expect(screen.getByTestId("table-view-run-picker")).toHaveClass("wb-run-version-picker");
    expect(screen.getByTestId("table-view-run-picker")).toHaveTextContent("Versions:");
    expect(screen.getByRole("button", { name: "Show results for run run_current" })).toHaveClass(
      "wb-run-version-picker__button",
    );

    fireEvent.click(screen.getByRole("button", { name: "Show results for run run_older" }));
    expect(setActiveRunId).toHaveBeenCalledWith("run_older");
  });

  it("keeps the compact Run identifier visible for a single-run project", async () => {
    mockDetail.current = emptyDetail;
    const ctx: LineageContextValue = { model: model("only-run"), selectedKey: null, select: () => {} };
    render(
      <MemoryRouter initialEntries={["/runs/only-run?project_root=/tmp/demo"]}>
        <ForestContext.Provider
          value={{
            forest: {
              heads: [{ runId: "only-run", createdAt: "2026-07-30T00:00:00Z" }],
              nodes: [],
              edges: [],
              familyCount: 1,
              familyRunCount: 1,
            } as never,
            activeRunId: "only-run",
            setActiveRunId: () => {},
          }}
        >
          <LineageContext.Provider value={ctx}>
            <TableView />
          </LineageContext.Provider>
        </ForestContext.Provider>
      </MemoryRouter>,
    );

    await waitFor(() => expect(detailCalls.current.length).toBeGreaterThan(0));
    expect(screen.getByTestId("table-view-run-picker")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Show results for run only-run" })).toHaveClass(
      "wb-run-version-picker__button",
    );
  });

  it("keeps every project Run pill available after a graph node is selected", async () => {
    const setActiveRunId = vi.fn();
    const ctx: LineageContextValue = { model: model("url-run"), selectedKey: null, select: () => {} };
    render(
      <MemoryRouter initialEntries={["/runs/url-run?project_root=/tmp/demo&tabs=node:older-only&active=node:older-only"]}>
        <WorkbenchStateProvider
          runId="run_current"
          validNodeKeys={new Set(["node:older-only"])}
        >
          <ForestContext.Provider
            value={{
              forest: {
                heads: [
                  { runId: "run_older", createdAt: "2026-07-29T00:00:00Z" },
                  { runId: "run_current", createdAt: "2026-07-30T00:00:00Z" },
                ],
                nodes: [{ nodeKey: "node:older-only", runs: ["run_older"] }],
                edges: [],
                familyCount: 1,
                familyRunCount: 2,
              } as never,
              activeRunId: "run_current",
              setActiveRunId,
            }}
          >
            <LineageContext.Provider value={ctx}>
              <TableView />
            </LineageContext.Provider>
          </ForestContext.Provider>
        </WorkbenchStateProvider>
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByTestId("table-view-empty")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Show results for run run_current" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Show results for run run_older" }));
    expect(setActiveRunId).toHaveBeenCalledWith("run_older");
  });

  it("wraps fixed-width result charts in a horizontal scroll region", async () => {
    mockArtifacts.current = {
      groups: [
        {
          artifact_type: "time_series_json",
          items: [
            {
              artifact_id: "ts.chart.series_transform",
              path: "artifacts/time_series/ts.chart.series_transform.json",
              artifact_type: "time_series_json",
              step: "time_series_diagnostics",
              sha256: "wide-chart",
            },
          ],
        },
      ],
    } as unknown as ArtifactsResponse;
    artifactJsonMock.mockResolvedValue({ payload: { rows: [] } });

    renderTable();

    const scrollRegion = await screen.findByTestId("table-view-time-series-scroll");
    expect(scrollRegion).toHaveClass("wb-result-artifact-scroll");
    expect(scrollRegion).toHaveAttribute("tabindex", "0");
  });

  it("asks AI about a figure using its numeric source context (G2)", async () => {
    mockArtifacts.current = {
      groups: [
        {
          artifact_type: "figure",
          items: [
            { artifact_id: "coef_plot", path: "figures/coef_plot.png", artifact_type: "figure", step: "viz", sha256: "a" },
          ],
        },
      ],
    } as unknown as ArtifactsResponse;
    figureCtxMock.mockResolvedValue({
      figure: { artifact_id: "coef_plot", chart_type: "coefficient plot" },
      source: { artifact_id: "ols_1", kind: "model", preview_json: "{}" },
      response_guardrails: {},
    });
    figureAskMock.mockResolvedValue({ text: "The education coefficient is positive and significant." });

    renderTable();

    await waitFor(() =>
      expect(screen.getByTestId("figure-ask-ai-button-coef_plot")).toBeTruthy(),
    );
    fireEvent.click(screen.getByTestId("figure-ask-ai-button-coef_plot"));

    await waitFor(() =>
      expect(screen.getByTestId("figure-ask-ai-answer-coef_plot")).toBeTruthy(),
    );
    expect(screen.getByTestId("figure-ask-ai-answer-coef_plot").textContent).toContain(
      "education coefficient",
    );
    // context fetched with (projectRoot, runId, artifactId); chart interpreted from numbers
    expect(figureCtxMock).toHaveBeenCalledWith("/tmp/demo", "run-1", "coef_plot");
    const askArgs = figureAskMock.mock.calls[0];
    expect((askArgs[0] as { source: { kind: string } }).source.kind).toBe("model");
  });

  it("logs the figure explanation so it appears in AI activity", async () => {
    // Node Ask AI and report generation both write activity records; figure
    // explanations were the one AI exchange that left no trace at all.
    localStorage.clear();
    const { loadAiActivity } = await import("../../aiActivity/aiActivityLog");
    mockArtifacts.current = {
      groups: [
        {
          artifact_type: "figure",
          items: [
            { artifact_id: "coef_plot", path: "figures/coef_plot.png", artifact_type: "figure", step: "viz", sha256: "a" },
          ],
        },
      ],
    } as unknown as ArtifactsResponse;
    figureCtxMock.mockResolvedValue({
      figure: { artifact_id: "coef_plot", chart_type: "coefficient plot" },
      source: { artifact_id: "ols_1", kind: "model", preview_json: "{}" },
      response_guardrails: {},
    });
    figureAskMock.mockResolvedValue({ text: "Positive and significant." });

    renderTable();
    await waitFor(() =>
      expect(screen.getByTestId("figure-ask-ai-button-coef_plot")).toBeTruthy(),
    );
    fireEvent.click(screen.getByTestId("figure-ask-ai-button-coef_plot"));
    await waitFor(() =>
      expect(screen.getByTestId("figure-ask-ai-answer-coef_plot")).toBeTruthy(),
    );

    const records = loadAiActivity("/tmp/demo");
    expect(records).toHaveLength(1);
    expect(records[0]).toMatchObject({
      kind: "ask_ai",
      node_key: "figure:coef_plot",
      status: "answered",
      answer: "Positive and significant.",
    });
  });

  it("restores a previous explanation after the tab was left and reopened", async () => {
    // Switching to Graph unmounts this view. The answer used to live only in
    // component state, so coming back showed an empty panel and the user had
    // to pay for the call again to see what they had already been told.
    localStorage.clear();
    mockArtifacts.current = {
      groups: [
        {
          artifact_type: "figure",
          items: [
            { artifact_id: "coef_plot", path: "figures/coef_plot.png", artifact_type: "figure", step: "viz", sha256: "a" },
          ],
        },
      ],
    } as unknown as ArtifactsResponse;
    figureCtxMock.mockResolvedValue({
      figure: { artifact_id: "coef_plot", chart_type: "coefficient plot" },
      source: { artifact_id: "ols_1", kind: "model", preview_json: "{}" },
      response_guardrails: {},
    });
    figureAskMock.mockResolvedValue({ text: "Remembered interpretation." });

    const first = renderTable();
    await waitFor(() =>
      expect(screen.getByTestId("figure-ask-ai-button-coef_plot")).toBeTruthy(),
    );
    fireEvent.click(screen.getByTestId("figure-ask-ai-button-coef_plot"));
    await waitFor(() =>
      expect(screen.getByTestId("figure-ask-ai-answer-coef_plot")).toBeTruthy(),
    );
    first.unmount();

    figureAskMock.mockClear();
    renderTable();

    await waitFor(() =>
      expect(screen.getByTestId("figure-ask-ai-answer-coef_plot").textContent).toContain(
        "Remembered interpretation",
      ),
    );
    // Restored from the log, not re-requested from the provider.
    expect(figureAskMock).not.toHaveBeenCalled();
  });

  it("renders Figure Ask AI Markdown instead of exposing marker syntax", async () => {
    mockArtifacts.current = {
      groups: [
        {
          artifact_type: "figure",
          items: [
            { artifact_id: "coef_plot", path: "figures/coef_plot.png", artifact_type: "figure", step: "viz", sha256: "a" },
          ],
        },
      ],
    } as unknown as ArtifactsResponse;
    figureCtxMock.mockResolvedValue({
      figure: { artifact_id: "coef_plot", chart_type: "coefficient plot" },
      source: { artifact_id: "ols_1", kind: "model", preview_json: "{}" },
      response_guardrails: {},
    });
    figureAskMock.mockResolvedValue({ text: "**Supported**\n\n- Review the interval." });

    renderTable();
    await waitFor(() => expect(screen.getByTestId("figure-ask-ai-button-coef_plot")).toBeTruthy());
    fireEvent.click(screen.getByTestId("figure-ask-ai-button-coef_plot"));
    const answer = await screen.findByTestId("figure-ask-ai-answer-coef_plot");
    expect(answer.textContent).toContain("Supported");
    expect(answer.textContent).toContain("Review the interval.");
    expect(answer.textContent).not.toContain("**");
  });
});

describe("TableView — figure vision opt-in (G2 step 2)", () => {
  const figureArtifacts = {
    groups: [
      {
        artifact_type: "figure",
        items: [
          { artifact_id: "coef_plot", path: "figures/coef_plot.png", artifact_type: "figure", step: "viz", sha256: "a" },
        ],
      },
    ],
  } as unknown as ArtifactsResponse;

  beforeEach(() => {
    // sibling describe → the outer beforeEach does not run here; reset explicitly
    // so per-test call assertions are not polluted by earlier tests.
    mockDetail.current = emptyDetail;
    detailCalls.current = [];
    artifactCalls.current = [];
    figureCtxMock.mockReset();
    figureAskMock.mockReset();
    figureImageMock.mockReset();
    llmConfigMock.mockReset();
    mockArtifacts.current = figureArtifacts;
    figureCtxMock.mockResolvedValue({
      figure: { artifact_id: "coef_plot", chart_type: "coefficient plot" },
      source: { artifact_id: "ols_1", kind: "model", preview_json: "{}" },
      response_guardrails: {},
    });
    figureAskMock.mockResolvedValue({ text: "interpretation" });
  });

  it("hides the image opt-in when the model is not vision-capable", async () => {
    llmConfigMock.mockResolvedValue({ configured: true, supports_vision: false });
    renderTable();
    await waitFor(() => expect(screen.getByTestId("figure-ask-ai-button-coef_plot")).toBeTruthy());
    expect(screen.queryByTestId("figure-send-image-coef_plot")).toBeNull();
  });

  it("offers a default-off opt-in naming the provider when vision is available", async () => {
    llmConfigMock.mockResolvedValue({
      configured: true,
      supports_vision: true,
      provider_name: "DeepSeek",
      model: "vmodel",
    });
    renderTable();
    await waitFor(() => expect(screen.getByTestId("figure-send-image-coef_plot")).toBeTruthy());

    const optIn = screen.getByTestId("figure-send-image-coef_plot");
    expect(optIn.textContent).toContain("DeepSeek");
    expect(optIn.textContent).toContain("leaves your machine");
    expect(screen.getByRole("checkbox")).not.toBeChecked();

    // not opted in → no image travels
    fireEvent.click(screen.getByTestId("figure-ask-ai-button-coef_plot"));
    await waitFor(() => expect(figureAskMock).toHaveBeenCalled());
    expect(figureAskMock.mock.calls[0][2]).toBeUndefined();
    expect(figureImageMock).not.toHaveBeenCalled();
  });

  it("sends the rendered PNG only after the user opts in", async () => {
    llmConfigMock.mockResolvedValue({
      configured: true,
      supports_vision: true,
      provider_name: "DeepSeek",
      model: "vmodel",
    });
    figureImageMock.mockResolvedValue("data:image/png;base64,AAAA");
    renderTable();
    await waitFor(() => expect(screen.getByTestId("figure-send-image-coef_plot")).toBeTruthy());

    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByTestId("figure-ask-ai-button-coef_plot"));

    await waitFor(() => expect(figureAskMock).toHaveBeenCalled());
    expect(figureImageMock).toHaveBeenCalled();
    expect(figureAskMock.mock.calls[0][2]).toBe("data:image/png;base64,AAAA");
  });
});
