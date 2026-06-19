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

  it("renders both rm and sd panels when both tracks are ok", () => {
    const withHonest: CSDiagnostics = {
      ...diag,
      honest_did: {
        rm: {
          status: "ok",
          reason: null,
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
        sd: {
          status: "ok",
          reason: null,
          method: "FLCI",
          num_pre: 2,
          num_post: 2,
          m_grid: [0.0, 0.01, 0.02],
          scale: 1.0,
          post_average: {
            results: [
              { M: 0.0, lb: 1.2, ub: 3.0 },
              { M: 0.01, lb: 0.9, ub: 3.3 },
              { M: 0.02, lb: 0.5, ub: 3.7 },
            ],
            breakdown: 0.02,
          },
          per_event_time: [
            {
              event_time: 1,
              results: [
                { M: 0.0, lb: 1.0, ub: 2.8 },
                { M: 0.01, lb: 0.7, ub: 3.1 },
              ],
              breakdown: null,
            },
          ],
        },
      },
    };
    render(<CSDiagnosticsCard diagnostics={withHonest} />);
    expect(screen.getByLabelText("cs-honest-did-panel")).toBeInTheDocument();
    expect(screen.getByLabelText("cs-honest-did-rm-panel")).toBeInTheDocument();
    expect(screen.getByLabelText("cs-honest-did-sd-panel")).toBeInTheDocument();
    expect(
      screen.getByLabelText("cs-honest-did-rm-post-average"),
    ).toBeInTheDocument();
    expect(
      screen.getByLabelText("cs-honest-did-sd-post-average"),
    ).toBeInTheDocument();
    expect(
      screen.getByLabelText("cs-honest-did-rm-event-0"),
    ).toBeInTheDocument();
    expect(
      screen.getByLabelText("cs-honest-did-sd-event-1"),
    ).toBeInTheDocument();
    // sd post-average renders an M row (0.0100 -> 0.01 at 2dp)
    const sdPost = screen.getByLabelText("cs-honest-did-sd-post-average");
    expect(sdPost.textContent).toContain("0.01");
    // rm post-average breakdown M̄ (1.00) surfaces in its own div
    const postBreakdown = screen
      .getByLabelText("cs-honest-did-rm-post-average")
      .parentElement!.querySelector("div");
    expect(postBreakdown?.textContent).toContain("突破");
    expect(postBreakdown?.textContent).toContain("1.00");
    // null breakdown microcopy for the per-event-time rows
    expect(screen.getAllByText(/无突破/).length).toBeGreaterThan(0);
  });

  it("renders a null (nan-sanitized) honest-DID CI row as — without crashing", () => {
    // The backend coerces a degenerate (nan, nan) CI to JSON null (lb/ub = null).
    // The card MUST render those as the em-dash "—" via the `f` helper, never
    // "null"/"NaN", and must not throw.
    const withNullCI: CSDiagnostics = {
      ...diag,
      honest_did: {
        rm: {
          status: "ok",
          reason: null,
          num_pre: 2,
          num_post: 2,
          mbar_grid: [0.0, 1.0],
          post_average: {
            results: [
              { Mbar: 0.0, lb: null, ub: null },
              { Mbar: 1.0, lb: 0.4, ub: 3.6 },
            ],
            breakdown: null,
          },
          per_event_time: [
            {
              event_time: 0,
              results: [{ Mbar: 0.0, lb: null, ub: null }],
              breakdown: null,
            },
          ],
        },
        sd: { status: "not_available", reason: "HONEST_NO_PRE_PERIODS" },
      },
    };
    expect(() =>
      render(<CSDiagnosticsCard diagnostics={withNullCI} />),
    ).not.toThrow();
    const panel = screen.getByLabelText("cs-honest-did-rm-post-average");
    expect(panel.textContent).toContain("—");
    expect(panel.textContent).not.toContain("null");
    expect(panel.textContent).not.toContain("NaN");
  });

  it("renders the sd-unavailable note (with reason) while rm still renders", () => {
    const sdUnavail: CSDiagnostics = {
      ...diag,
      honest_did: {
        rm: {
          status: "ok",
          reason: null,
          num_pre: 2,
          num_post: 2,
          mbar_grid: [0.5, 1.0],
          post_average: {
            results: [
              { Mbar: 0.5, lb: 0.8, ub: 3.2 },
              { Mbar: 1.0, lb: 0.4, ub: 3.6 },
            ],
            breakdown: 1.0,
          },
          per_event_time: [],
        },
        sd: { status: "not_available", reason: "HONEST_NO_PRE_PERIODS" },
      },
    };
    render(<CSDiagnosticsCard diagnostics={sdUnavail} />);
    const sdU = screen.getByLabelText("cs-honest-did-sd-unavailable");
    expect(sdU).toBeInTheDocument();
    expect(sdU.textContent).toContain("HONEST_NO_PRE_PERIODS");
    // rm panel still renders
    expect(screen.getByLabelText("cs-honest-did-rm-panel")).toBeInTheDocument();
    // no sd ok panel
    expect(screen.queryByLabelText("cs-honest-did-sd-panel")).toBeNull();
  });

  it("type-checks + renders a not_available sd track carrying the FULL backend-echoed extra (method/m_grid/scale, no post_average)", () => {
    // The adapter echoes `extra` (method/m_grid/scale) on the HonestDiDError
    // (not_available) path too — so the on-disk degraded sd track is RICHER than
    // {status, reason}. This must still type-check against HonestTrack (those
    // fields optional) and render the unavailable note without crashing.
    const sdRichDegraded: CSDiagnostics = {
      ...diag,
      honest_did: {
        rm: {
          status: "not_available",
          reason: "HONEST_NO_PRE_PERIODS: ΔRM requires at least one pre-period.",
          num_pre: 0,
          num_post: 2,
          mbar_grid: [0.0, 1.0],
        },
        sd: {
          status: "not_available",
          reason: "HONEST_NO_PRE_PERIODS: ΔSD requires at least one pre-period.",
          num_pre: 0,
          num_post: 2,
          method: "FLCI",
          m_grid: [0.0, 0.5, 1.0, 1.5, 2.0],
          scale: 0.42,
          // intentionally NO post_average / per_event_time (degraded path)
        },
      },
    };
    render(<CSDiagnosticsCard diagnostics={sdRichDegraded} />);
    const sdU = screen.getByLabelText("cs-honest-did-sd-unavailable");
    expect(sdU.textContent).toContain("HONEST_NO_PRE_PERIODS");
    const rmU = screen.getByLabelText("cs-honest-did-rm-unavailable");
    expect(rmU.textContent).toContain("HONEST_NO_PRE_PERIODS");
    // neither ok panel renders
    expect(screen.queryByLabelText("cs-honest-did-sd-panel")).toBeNull();
    expect(screen.queryByLabelText("cs-honest-did-rm-panel")).toBeNull();
  });

  it("type-checks an ok sd track whose rows carry null (nan-sanitized) M lb/ub", () => {
    // Backend sanitizes a degenerate FLCI CI to JSON null; the sd row's lb/ub
    // must be assignable from `number | null` and render as — without crashing.
    const sdNull: CSDiagnostics = {
      ...diag,
      honest_did: {
        rm: { status: "not_available", reason: "skip" },
        sd: {
          status: "ok",
          reason: null,
          num_pre: 2,
          num_post: 1,
          method: "FLCI",
          m_grid: [0.0, 0.5, 1.0],
          scale: 0.1,
          post_average: {
            results: [
              { M: 0.0, lb: 0.5, ub: 1.5 },
              { M: 0.5, lb: null, ub: null },
            ],
            breakdown: null,
          },
          per_event_time: [
            {
              event_time: 0,
              results: [{ M: 0.0, lb: null, ub: null }],
              breakdown: null,
            },
          ],
        },
      },
    };
    render(<CSDiagnosticsCard diagnostics={sdNull} />);
    const panel = screen.getByLabelText("cs-honest-did-sd-post-average");
    expect(panel.textContent).toContain("—");
  });

  it("renders the degraded note (with reason) for a degraded track", () => {
    const degraded: CSDiagnostics = {
      ...diag,
      honest_did: {
        rm: { status: "degraded", reason: "rm solver did not converge" },
        sd: { status: "degraded", reason: "sd FLCI returned non-finite" },
      },
    };
    render(<CSDiagnosticsCard diagnostics={degraded} />);
    expect(
      screen.getByLabelText("cs-honest-did-rm-degraded"),
    ).toBeInTheDocument();
    expect(screen.getByText(/rm solver did not converge/)).toBeInTheDocument();
    expect(
      screen.getByLabelText("cs-honest-did-sd-degraded"),
    ).toBeInTheDocument();
    expect(screen.getByText(/sd FLCI returned non-finite/)).toBeInTheDocument();
    // panel wrapper still present
    expect(screen.getByLabelText("cs-honest-did-panel")).toBeInTheDocument();
    // no ok sub-panels
    expect(screen.queryByLabelText("cs-honest-did-rm-panel")).toBeNull();
    expect(screen.queryByLabelText("cs-honest-did-sd-panel")).toBeNull();
  });

  it("renders no honest-DID panel when honest_did is absent (degraded-safe)", () => {
    render(<CSDiagnosticsCard diagnostics={diag} />);
    expect(screen.queryByLabelText("cs-honest-did-panel")).toBeNull();
    expect(screen.queryByLabelText("cs-honest-did-rm-panel")).toBeNull();
    expect(screen.queryByLabelText("cs-honest-did-sd-panel")).toBeNull();
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
