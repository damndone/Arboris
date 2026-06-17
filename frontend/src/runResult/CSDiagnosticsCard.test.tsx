import "@testing-library/jest-dom/vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { CSDiagnosticsCard, type CSDiagnostics } from "./CSDiagnosticsCard";

const diag: CSDiagnostics = {
  att_gt: [
    { g: 2, t: 2, event_time: 0, att: 1.8, se: 0.4, n_treated: 10,
      n_control: 20, valid: true, warning: null },
    { g: 2, t: 3, event_time: 1, att: 2.4, se: 0.5, n_treated: 10,
      n_control: 20, valid: true, warning: null },
  ],
  aggregations: {
    simple: { overall: 2.1, overall_se: 0.41, overall_uniform_band: [1.3, 2.9],
      label_kind: "none", label: [], estimate: [], se: [] },
    dynamic: { overall: 2.1, overall_se: 0.41, label_kind: "event_time",
      event_time: [-1, 0, 1], estimate: [0.0, 1.8, 2.4], se: [0.3, 0.4, 0.5],
      pointwise_ci: [[-0.6, 0.6], [1.0, 2.6], [1.4, 3.4]],
      uniform_band: [[-0.7, 0.7], [0.9, 2.7], [1.3, 3.5]], uniform_crit: 2.34 },
    group: { overall: 2.1, overall_se: 0.41, label_kind: "cohort",
      label: [2, 3], estimate: [2.0, 1.5], se: [0.4, 0.5],
      pointwise_ci: [[1.2, 2.8], [0.5, 2.5]],
      uniform_band: [[1.1, 2.9], [0.4, 2.6]], uniform_crit: 2.3 },
    calendar: { overall: 2.1, overall_se: 0.41, label_kind: "period",
      label: [2, 3], estimate: [1.7, 2.3], se: [0.4, 0.5],
      pointwise_ci: [[0.9, 2.5], [1.3, 3.3]],
      uniform_band: [[0.8, 2.6], [1.2, 3.4]], uniform_crit: 2.3 },
  },
  diagnostics: { overlap: { ps_min: 0.05, ps_max: 0.95 }, omitted_cells: [],
    sample_spec: {} },
  warnings: [],
  metadata: { control_group: "never_treated", est_method: "dr",
    base_period: "varying", anticipation: 0, covariates: ["x1"],
    cluster_var: null, n_units: 100, n_cohorts: 2, n_valid_cells: 4,
    n_cells: 4, B: 999, alpha: 0.05, seed: 42, confidence_level: 0.95,
    band_type: "uniform" },
};

describe("CSDiagnosticsCard", () => {
  it("renders overall ATT and the event-study chart", () => {
    render(<CSDiagnosticsCard diagnostics={diag} />);
    expect(screen.getByText(/2\.10/)).toBeInTheDocument();
    expect(screen.getByLabelText("cs-event-study-chart")).toBeInTheDocument();
  });

  it("renders a degraded state with the error message", () => {
    render(
      <CSDiagnosticsCard
        diagnostics={{ available: false, error: "cs_did failed: boom" }}
      />,
    );
    expect(screen.getByText(/不可用/)).toBeInTheDocument();
    expect(screen.getByText(/boom/)).toBeInTheDocument();
  });

  it("renders warning strings when warnings is non-empty", () => {
    const warned: CSDiagnostics = { ...diag,
      warnings: ["thin support in cohort 3"] };
    render(<CSDiagnosticsCard diagnostics={warned} />);
    expect(screen.getByText(/thin support in cohort 3/)).toBeInTheDocument();
  });

  it("renders nothing when diagnostics is undefined", () => {
    const { container } = render(<CSDiagnosticsCard diagnostics={undefined} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders a 结果不完整 fallback for a truthy-but-incomplete artifact", () => {
    // available is not false (so it passes the degraded check) but a required
    // aggregation key is missing — must NOT throw on d.aggregations.dynamic.*.
    const partial = {
      ...diag,
      aggregations: { simple: diag.aggregations.simple },
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any as CSDiagnostics;
    expect(() =>
      render(<CSDiagnosticsCard diagnostics={partial} />),
    ).not.toThrow();
    expect(screen.getByText(/结果不完整/)).toBeInTheDocument();
  });

  it("renders the honest-DID sensitivity panel with a breakdown value", () => {
    const withHonest: CSDiagnostics = {
      ...diag,
      honest_did: {
        skipped: false,
        num_pre: 2,
        num_post: 2,
        mbar_grid: [0.5, 1.0, 1.5],
        post_average: {
          results: [
            { Mbar: 0.5, lb: 0.8, ub: 3.2 },
            { Mbar: 1.0, lb: 0.4, ub: 3.6 },
            { Mbar: 1.5, lb: -0.1, ub: 4.1 },
          ],
          breakdown: 1.0,
        },
        per_event_time: [
          {
            event_time: 0,
            results: [
              { Mbar: 0.5, lb: 0.9, ub: 2.7 },
              { Mbar: 1.0, lb: 0.5, ub: 3.1 },
            ],
            breakdown: null,
          },
        ],
      },
    };
    render(<CSDiagnosticsCard diagnostics={withHonest} />);
    expect(screen.getByLabelText("cs-honest-did-panel")).toBeInTheDocument();
    expect(
      screen.getByLabelText("cs-honest-did-post-average"),
    ).toBeInTheDocument();
    // post-average breakdown M̄ (1.00) surfaces in its own div
    const postBreakdown = screen
      .getByLabelText("cs-honest-did-post-average")
      .parentElement!.querySelector("div");
    expect(postBreakdown?.textContent).toContain("突破 M̄: 1.00");
    // null breakdown microcopy for the per-event-time row
    expect(screen.getByText(/无突破/)).toBeInTheDocument();
  });

  it("renders the skipped note when honest_did is degraded", () => {
    const skipped: CSDiagnostics = {
      ...diag,
      honest_did: {
        skipped: true,
        reason: "需要至少 1 个 pre 期",
        num_pre: 0,
        num_post: 2,
      },
    };
    render(<CSDiagnosticsCard diagnostics={skipped} />);
    expect(
      screen.getByLabelText("cs-honest-did-skipped"),
    ).toBeInTheDocument();
    expect(screen.getByText(/需要至少 1 个 pre 期/)).toBeInTheDocument();
  });

  it("renders no honest-DID panel when honest_did is absent (degraded-safe)", () => {
    render(<CSDiagnosticsCard diagnostics={diag} />);
    expect(screen.queryByLabelText("cs-honest-did-panel")).toBeNull();
    expect(screen.queryByLabelText("cs-honest-did-skipped")).toBeNull();
  });

  it("renders an unavailable note when dynamic event_time is empty", () => {
    const noEs: CSDiagnostics = { ...diag,
      aggregations: { ...diag.aggregations,
        dynamic: { ...diag.aggregations.dynamic, event_time: [],
          estimate: [], se: [], pointwise_ci: [], uniform_band: [] } } };
    render(<CSDiagnosticsCard diagnostics={noEs} />);
    expect(screen.queryByLabelText("cs-event-study-chart")).toBeNull();
    expect(screen.getByText(/事件研究不可用/)).toBeInTheDocument();
  });
});
