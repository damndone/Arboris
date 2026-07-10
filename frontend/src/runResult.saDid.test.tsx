import "@testing-library/jest-dom/vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { RunResultView } from "./runResult";
import type { CSDiagnostics } from "./runResult/CSDiagnosticsCard";

type FetchInit = { status?: number; ok?: boolean };

function jsonResponse(body: unknown, init: FetchInit = {}): Response {
  const status = init.status ?? 200;
  return {
    ok: init.ok ?? (status >= 200 && status < 300),
    status,
    json: () => Promise.resolve(body),
  } as unknown as Response;
}

// Sun-Abraham writes the SAME sa_did.json shape as Callaway-Sant'Anna's
// cs_did.json (dynamic event study + nested honest_did {rm,sd}), only the
// metadata.estimator differs ("sun_abraham"). The card is reused verbatim.
const saDiag: CSDiagnostics = {
  att_gt: [
    { g: 2, t: 2, event_time: 0, att: 1.8, se: 0.4, n_treated: 10,
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
      label: [2], estimate: [2.0], se: [0.4],
      pointwise_ci: [[1.2, 2.8]], uniform_band: [[1.1, 2.9]], uniform_crit: 2.3 },
    calendar: { overall: 2.1, overall_se: 0.41, label_kind: "period",
      label: [2], estimate: [1.7], se: [0.4],
      pointwise_ci: [[0.9, 2.5]], uniform_band: [[0.8, 2.6]], uniform_crit: 2.3 },
  },
  diagnostics: { overlap: { ps_min: null, ps_max: null }, omitted_cells: [],
    sample_spec: {} },
  honest_did: {
    rm: {
      status: "ok", reason: null, num_pre: 1, num_post: 2,
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
  warnings: [],
  metadata: {
    control_group: "not_yet_treated", est_method: "saturated_ols",
    base_period: "varying", anticipation: 0, covariates: [],
    cluster_var: null, n_units: 100, n_cohorts: 2, n_valid_cells: 3,
    n_cells: 3, B: 0, alpha: 0.05, seed: 42, confidence_level: 0.95,
    band_type: "uniform",
    // estimator marker — present on the SA artifact, drives the card heading.
    estimator: "sun_abraham",
  },
};

const detail = {
  run_id: "run-sa",
  status: "completed",
  mode: "auto",
  started_at: "2026-06-20T00:00:00+00:00",
  y: "y",
  x: ["x1"],
  lineage: [],
  artifact_counts: {},
  errors: { issues: [] },
};

let fetchMock: ReturnType<typeof vi.fn<typeof fetch>>;
const originalFetch = globalThis.fetch;

beforeEach(() => {
  fetchMock = vi.fn<typeof fetch>();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  // Restore only fetch — vi.unstubAllGlobals() would also wipe the
  // ResizeObserver stub installed once in vitest.setup.ts (needed by React Flow).
  globalThis.fetch = originalFetch;
  vi.restoreAllMocks();
  vi.clearAllMocks();
});

test("fetches the sa_did artifact into the CS card (event-study + honest panels render)", async () => {
  fetchMock.mockImplementation((url) => {
    const u = String(url);
    // artifact JSON body for sa_did
    if (u.includes("/artifacts/sa_did")) {
      return Promise.resolve(jsonResponse(saDiag));
    }
    // artifacts listing — advertise the sa_did artifact (NOT cs_did)
    if (u.includes("/artifacts")) {
      return Promise.resolve(
        jsonResponse({
          groups: [
            {
              artifact_type: "effect_estimate",
              items: [
                { artifact_id: "sa_did", path: "sa_did.json", step: "estimation" },
              ],
            },
          ],
        }),
      );
    }
    // run detail
    if (u.includes("/runs/run-sa")) {
      return Promise.resolve(jsonResponse(detail));
    }
    return Promise.resolve(jsonResponse({}));
  });

  render(
    <RunResultView projectRoot="/tmp/test" runId="run-sa" onError={() => {}} />,
  );

  // event-study chart from the dynamic aggregation
  await waitFor(() => {
    expect(screen.getByLabelText("cs-event-study-chart")).toBeInTheDocument();
  });
  // nested honest-DID panel renders (rm ok track)
  expect(screen.getByLabelText("cs-honest-did-panel")).toBeInTheDocument();
  expect(screen.getByLabelText("cs-honest-did-rm-panel")).toBeInTheDocument();
  // estimator-aware heading: an SA run must NOT be mislabeled Callaway-Sant'Anna
  expect(
    screen.getByText("Sun-Abraham (interaction-weighted) DID"),
  ).toBeInTheDocument();
  expect(screen.queryByText("Callaway-Sant'Anna DID")).toBeNull();
});
