import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { LineageContext } from "../../lineage/LineageContext";
import type { LineageContextValue } from "../../lineage/LineageContext";
import { ForestContext } from "../ForestContext";
import type { GraphViewModel } from "../../lineage/api/graphViewTypes";
import type { ArtifactsResponse, RunDetail } from "../../api";
import { TableView } from "./TableView";

const mockDetail = vi.hoisted(() => ({ current: null as unknown }));
const mockArtifacts = vi.hoisted(() => ({ current: null as unknown }));
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
          nobs: 100,
          coefficients: {
            education: { estimate: 0.08, std_error: 0.01, p_value: 0.001, p_value_display: "<0.001" },
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
    // human-readable caption/alt
    expect(imgs[0].getAttribute("alt")).toContain("correlation_heatmap");
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
});
