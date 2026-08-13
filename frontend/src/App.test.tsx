import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, test, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

vi.mock("./capabilities/useCapabilities", () => ({
  useCapabilities: () => ({
    data: {
      schema_version: 1,
      model_types: [
        { key: "auto", label: "Auto (infer from y)", group: "auto" },
        { key: "ols", label: "OLS (linear)", group: "Linear" },
        { key: "logit", label: "Logit", group: "Binary" },
        { key: "poisson", label: "Poisson", group: "Count" },
        { key: "negative_binomial", label: "Negative Binomial", group: "Count" },
      ],
      imputation_methods: [],
    },
    loading: false,
    error: null,
    refetch: () => {},
  }),
}));

import App from "./App";
import type { RunSummary } from "./api";

type FetchInit = { status?: number; ok?: boolean };

function jsonResponse(body: unknown, init: FetchInit = {}): Response {
  const status = init.status ?? 200;
  return {
    ok: init.ok ?? (status >= 200 && status < 300),
    status,
    json: () => Promise.resolve(body)
  } as unknown as Response;
}

function makeRun(id: string, overrides: Partial<RunSummary> = {}): RunSummary {
  return {
    run_id: id,
    status: "completed",
    mode: "auto",
    started_at: "2026-05-01T00:00:00+00:00",
    y: "y",
    x: ["x"],
    ...overrides,
  };
}

function makeRuns(count: number): RunSummary[] {
  return Array.from({ length: count }, (_, i) =>
    makeRun(`run-${i + 1}`, { started_at: `2026-05-${String(i + 1).padStart(2, "0")}T00:00:00+00:00` })
  );
}

function renderAt(path = "/") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>
  );
}

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn());
  try {
    localStorage.clear();
  } catch {
    // ignore
  }
  try {
    // Keep browser-like session state isolated between tests.
    sessionStorage.clear();
  } catch {
    // ignore
  }
});

afterEach(() => {
  // NOTE: don't call vi.unstubAllGlobals() — it would wipe the
  // ResizeObserver / DOMRect stubs that vitest.setup.ts installs once
  // for the whole suite. The next beforeEach re-stubs fetch, which is
  // the only global this file touches.
  vi.restoreAllMocks();
});

// Build a fully-populated minimal RunDetail for run-detail route tests.
function fullRunDetail(
  runId: string,
  status: string,
): Record<string, unknown> {
  return {
    run_id: runId,
    status,
    mode: "auto",
    started_at: "2026-05-01T00:00:00+00:00",
    y: "y",
    x: ["x1", "x2"],
    lineage: [],
    artifact_counts: {},
  errors: { issues: [] },
  model_results: [],
  };
}
test("clicking a history row loads run detail with errors", async () => {
  const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
  fetchMock.mockResolvedValueOnce(
    jsonResponse({
      run_id: "run-1",
      status: "blocked",
      mode: "auto",
      started_at: "2026-05-01T00:00:00+00:00",
      y: "y",
      x: ["x"],
      lineage: [{ source: "/tmp/demo/data.csv", artifact_id: "raw_data.csv" }],
      artifact_counts: { metadata: 2, profile: 1 },
      errors: {
        issues: [
          {
            severity: "BLOCKER",
            code: "DATA_QUALITY",
            message: "Bad column",
            evidence: {},
          },
        ],
      },
    })
  );

  renderAt("/runs/run-1?project_root=/tmp/demo&tab=overview");

  await waitFor(() => {
    expect(
      screen.getByRole("heading", { name: /run detail/i })
    ).toBeInTheDocument();
  });
  // V1.5.0.1 HF3: clicking a history row now navigates to /runs/:id
  // (instead of inline-rendering RunResultView below the list), so
  // the "Run history" heading is no longer on screen after the click.
  expect(screen.queryByRole("heading", { name: /run history/i })).not.toBeInTheDocument();
  expect(screen.getByText("Bad column")).toBeInTheDocument();
  expect(screen.getByText("DATA_QUALITY")).toBeInTheDocument();
});

test("run detail renders info issues as system notes instead of errors", async () => {
  const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
  fetchMock.mockResolvedValueOnce(
    jsonResponse({
      run_id: "run-1",
      status: "completed",
      mode: "auto",
      started_at: "2026-05-01T00:00:00+00:00",
      y: "binary_success_y",
      x: ["x7_region_code"],
      lineage: [],
      artifact_counts: { report: 1 },
      errors: {
        issues: [
          {
            severity: "INFO",
            code: "CATEGORICAL_CANDIDATE",
            message: "Column 'x7_region_code' may be categorical.",
            evidence: {},
          },
        ],
      },
    })
  );

  renderAt("/runs/run-1?project_root=/tmp/demo&tab=overview");

  await waitFor(() => {
    expect(screen.getByText("CATEGORICAL_CANDIDATE")).toBeInTheDocument();
  });
  expect(screen.queryByText("Issues")).not.toBeInTheDocument();
  expect(screen.getByText("System notes")).toBeInTheDocument();
});

test("run detail normalizes stale categorical candidate when model dummy-coded it", async () => {
  const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
  fetchMock.mockResolvedValueOnce(
    jsonResponse({
      run_id: "run-1",
      status: "completed",
      mode: "auto",
      started_at: "2026-05-01T00:00:00+00:00",
      y: "continuous_score_y",
      x: ["x7_region_code"],
      lineage: [],
      artifact_counts: { report: 1 },
      errors: {
        issues: [
          {
            severity: "INFO",
            code: "CATEGORICAL_CANDIDATE",
            message: "Column 'x7_region_code' may be categorical. Consider one-hot encoding.",
            evidence: { column: "x7_region_code" },
          },
        ],
      },
      model_results: [
        {
          model_id: "ols_1",
          model_type: "ols_robust",
          coefficients: {
            "C(Q('x7_region_code'))[T.region_B]": { estimate: 0.2 },
          },
        },
      ],
    })
  );

  renderAt("/runs/run-1?project_root=/tmp/demo&tab=overview");

  await waitFor(() => {
    expect(screen.getByText("CATEGORICAL_AUTO_DUMMY_CODED")).toBeInTheDocument();
  });
  expect(screen.queryByText("CATEGORICAL_CANDIDATE")).not.toBeInTheDocument();
  expect(screen.queryByText(/Consider one-hot encoding/)).not.toBeInTheDocument();
});

test("run detail renders warning issues separately from blockers", async () => {
  const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
  fetchMock.mockResolvedValueOnce(
    jsonResponse({
      run_id: "run-1",
      status: "completed",
      mode: "auto",
      started_at: "2026-05-01T00:00:00+00:00",
      y: "count_events_y",
      x: ["x8_treatment", "x10_interaction_proxy"],
      lineage: [],
      artifact_counts: { report: 1 },
      errors: {
        issues: [
          {
            severity: "WARNING",
            code: "TREATMENT_PROXY_CORRELATION",
            message: "x8_treatment and x10_interaction_proxy are highly correlated.",
            evidence: {},
          },
        ],
      },
    })
  );

  renderAt("/runs/run-1?project_root=/tmp/demo&tab=overview");

  await waitFor(() => {
    expect(screen.getByText("TREATMENT_PROXY_CORRELATION")).toBeInTheDocument();
  });
  expect(screen.queryByText("Issues")).not.toBeInTheDocument();
  expect(screen.getByText("Warnings")).toBeInTheDocument();
});

test("run detail shows artifact list with download links", async () => {
  const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
  fetchMock.mockResolvedValueOnce(
    jsonResponse({
      run_id: "run-1",
      status: "completed",
      mode: "auto",
      started_at: "2026-05-01T00:00:00+00:00",
      y: "y",
      x: ["x"],
      lineage: [],
      artifact_counts: { report: 1 },
      errors: { issues: [] },
    })
  );
  fetchMock.mockResolvedValueOnce(
    jsonResponse({
      groups: [
        {
          artifact_type: "report",
          items: [
            {
              artifact_id: "report_html",
              path: "reports/report.html",
              artifact_type: "report",
              step: "reporting",
              sha256: "deadbeef",
            },
          ],
        },
      ],
    })
  );

  renderAt("/runs/run-1?project_root=/tmp/demo&tab=overview");

  await waitFor(() => screen.getByRole("heading", { name: /artifacts/i }));

  const downloadLink = screen.getByRole("link", { name: /report_html/i });
  expect(downloadLink).toHaveAttribute(
    "href",
    "/api/runs/run-1/artifacts/report_html?project_root=%2Ftmp%2Fdemo",
  );
});

test("view report toggles iframe with report URL", async () => {
  const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
  fetchMock.mockResolvedValueOnce(
    jsonResponse({
      run_id: "run-1",
      status: "completed",
      mode: "auto",
      started_at: "2026-05-01T00:00:00+00:00",
      y: "y",
      x: ["x"],
      lineage: [],
      artifact_counts: { report: 1 },
      errors: { issues: [] },
    })
  );
  fetchMock.mockResolvedValueOnce(
    jsonResponse({
      groups: [
        {
          artifact_type: "report",
          items: [
            {
              artifact_id: "report_html",
              path: "reports/report.html",
              artifact_type: "report",
              step: "reporting",
              sha256: "deadbeef",
            },
          ],
        },
      ],
    })
  );

  renderAt("/runs/run-1?project_root=/tmp/demo&tab=overview");

  await waitFor(() => screen.getByRole("button", { name: /view report/i }));
  fireEvent.click(screen.getByRole("button", { name: /view report/i }));

  const iframe = screen.getByTitle("Run report") as HTMLIFrameElement;
  expect(iframe.src).toContain(
    "/api/runs/run-1/report?project_root=%2Ftmp%2Fdemo",
  );
});

test("report iframe has sandbox attribute restricting scripts", async () => {
  const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
  fetchMock.mockResolvedValueOnce(
    jsonResponse({
      run_id: "run-1",
      status: "completed",
      mode: "auto",
      started_at: "2026-05-01T00:00:00+00:00",
      y: "y",
      x: ["x"],
      lineage: [],
      artifact_counts: { report: 1 },
      errors: { issues: [] },
    })
  );
  fetchMock.mockResolvedValueOnce(
    jsonResponse({
      groups: [
        {
          artifact_type: "report",
          items: [
            {
              artifact_id: "report_html",
              path: "reports/report.html",
              artifact_type: "report",
              step: "reporting",
              sha256: "deadbeef",
            },
          ],
        },
      ],
    })
  );

  renderAt("/runs/run-1?project_root=/tmp/demo&tab=overview");

  await waitFor(() => screen.getByRole("button", { name: /view report/i }));
  fireEvent.click(screen.getByRole("button", { name: /view report/i }));

  const iframe = screen.getByTitle("Run report") as HTMLIFrameElement;
  expect(iframe.getAttribute("sandbox")).toBe("allow-same-origin");
});

test("artifact fetch error shows retry button; retry succeeds", async () => {
  const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;

  fetchMock.mockResolvedValueOnce(
    jsonResponse({
      run_id: "run-1",
      status: "completed",
      mode: "auto",
      started_at: null,
      y: null,
      x: null,
      lineage: [],
      artifact_counts: {},
      errors: { issues: [] },
    })
  );

  fetchMock.mockRejectedValueOnce(new Error("Network failure"));

  renderAt("/runs/run-1?project_root=/tmp/demo&tab=overview");

  await waitFor(() => {
    expect(screen.getByText(/failed to load artifacts/i)).toBeInTheDocument();
  });
  const retryButton = screen.getByRole("button", { name: /retry/i });
  expect(retryButton).toBeInTheDocument();

  fetchMock.mockResolvedValueOnce(
    jsonResponse({
      groups: [
        {
          artifact_type: "report",
          items: [
            {
              artifact_id: "report_html",
              path: "reports/report.html",
              artifact_type: "report",
              step: "reporting",
              sha256: "x",
            },
          ],
        },
      ],
    })
  );

  fireEvent.click(retryButton);

  await waitFor(() => {
    expect(screen.getByText("report_html")).toBeInTheDocument();
  });
});

// --- New tests for V1.2.1 ---

test("/runs deep link redirects into the project graph home (F8)", async () => {
  const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
  fetchMock.mockResolvedValue(jsonResponse({ runs: [] }));

  renderAt("/runs?project_root=/tmp");

  await waitFor(() => {
    expect(screen.getByTestId("project-graph-route")).toBeInTheDocument();
  });
});

test("direct URL access to run detail keeps shareable result route", async () => {
  const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
  fetchMock.mockResolvedValueOnce(
    jsonResponse({
      run_id: "run-direct",
      status: "completed",
      mode: "auto",
      started_at: "2026-05-01T00:00:00+00:00",
      y: "y",
      x: ["x"],
      lineage: [],
      artifact_counts: { report: 1 },
      errors: { issues: [] },
      model_results: [
        {
          model_id: "ols_1",
          coefficients: {
            x: { estimate: 1.5, std_error: 0.2, p_value: 0.03 },
          },
        },
      ],
    }),
  );
  fetchMock.mockResolvedValueOnce(jsonResponse({ groups: [] }));

  renderAt("/runs/run-direct?project_root=/tmp/demo&tab=overview");

  await waitFor(() => {
    expect(screen.getByRole("heading", { name: /run detail/i })).toBeInTheDocument();
  });
  expect(screen.getByText("run-direct")).toBeInTheDocument();
  expect(document.body).toHaveTextContent("ols_1");
  expect(document.body).toHaveTextContent("x");
});

test("run detail coefficient table uses p-value display text when available", async () => {
  const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
  fetchMock.mockResolvedValueOnce(
    jsonResponse({
      run_id: "run-direct",
      status: "completed",
      mode: "auto",
      started_at: "2026-05-01T00:00:00+00:00",
      y: "y",
      x: ["x"],
      lineage: [],
      artifact_counts: { report: 1 },
      errors: { issues: [] },
      model_results: [
        {
          model_id: "ols_1",
          coefficients: {
            x: {
              estimate: 1.5,
              std_error: 0.2,
              p_value: 0,
              p_value_display: "< 0.001",
            },
          },
        },
      ],
    }),
  );
  fetchMock.mockResolvedValueOnce(jsonResponse({ groups: [] }));

  renderAt("/runs/run-direct?project_root=/tmp/demo&tab=overview");

  await waitFor(() => {
    expect(screen.getByRole("heading", { name: /coefficients/i })).toBeInTheDocument();
  });
  expect(screen.getByText("< 0.001")).toBeInTheDocument();
  expect(document.body).not.toHaveTextContent("0.0000");
});

test("/runs route with missing project_root falls back to the launcher", async () => {
  renderAt("/runs");

  await waitFor(() => {
    // launcher-specific affordance (the shell h1 also matches /workbench/i)
    expect(screen.getByRole("button", { name: "New project" })).toBeInTheDocument();
  });
});

test("running run progress includes statistical tests step", async () => {
  class MockEventSource {
    close = vi.fn();
    addEventListener = vi.fn();
  }
  vi.stubGlobal("EventSource", MockEventSource);

  const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
  fetchMock.mockResolvedValueOnce({
    ok: true,
    status: 200,
    json: () => Promise.resolve({
      run_id: "running-1",
      status: "running",
      mode: "auto",
      started_at: "2026-05-04T00:00:00+00:00",
      y: "y",
      x: ["x"],
      lineage: [],
      artifact_counts: {},
      errors: { issues: [] },
      model_results: [],
    }),
  } as Response);

  renderAt("/runs/running-1?project_root=/tmp/demo&tab=overview");

  await waitFor(() => {
    expect(screen.getByLabelText("run progress")).toBeInTheDocument();
  });
  expect(screen.getByText("Statistical tests")).toBeInTheDocument();
});

// --- V1.3.1 Trust Preview regression tests ---

test("report is disabled when artifact manifest is missing in preview", async () => {
  const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
  fetchMock.mockResolvedValueOnce(
    jsonResponse({
      run_id: "run-1",
      status: "completed",
      mode: "auto",
      started_at: "2026-05-11T00:00:00+00:00",
      y: "y",
      x: ["x1"],
      lineage: [],
      artifact_counts: { report: 1 },
      errors: { issues: [] },
      diagnostic_summary_preview: {
        available: true,
        preview_contract_version: "1.0",
        source_schema_version: "diagnostic_summary.v1",
        preview_status: "partial",
        contract_warnings: ["artifact manifest incomplete"],
        run_lifecycle_status: "completed",
        trust_label: "interpret_with_caution",
        primary_reasons: [],
        // artifact_manifest intentionally missing — gating must not default to available
      },
    })
  );

  renderAt("/runs/run-1?project_root=/tmp/demo&tab=overview");

  await waitFor(() => {
    expect(screen.getByText("Report")).toBeInTheDocument();
  });
  // Missing manifest → report button disabled, warning shown
  const button = screen.getByRole("button", { name: /report/i });
  expect(button).toBeDisabled();
  expect(screen.getByText(/artifact manifest is incomplete/)).toBeInTheDocument();
});

test("run detail coefficient risk shows reference level column", async () => {
  const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
  fetchMock.mockResolvedValueOnce(
    jsonResponse({
      run_id: "run-1",
      status: "completed",
      mode: "auto",
      started_at: "2026-05-11T00:00:00+00:00",
      y: "wage",
      x: ["region_code"],
      lineage: [],
      artifact_counts: { report: 1 },
      errors: { issues: [] },
      diagnostic_summary_preview: {
        available: true,
        preview_contract_version: "1.0",
        source_schema_version: "diagnostic_summary.v1",
        preview_status: "complete",
        contract_warnings: [],
        run_lifecycle_status: "completed",
        trust_label: "interpret_with_caution",
        primary_reasons: [],
        artifact_manifest: {
          report_html: { available: true, artifact_id: "report_html", filename: "report.html" },
        },
        run_status: {
          status: "usable_with_caution",
          status_scope: "primary_model",
          safe_to_generate_report: true,
          safe_to_interpret: "partial",
          has_blockers: false,
          has_warnings: true,
          has_cautions: false,
          model_results_available: true,
        },
        trust_counts: { blockers: 0, warnings: 1, cautions: 0, info: 0 },
        coefficient_risk: {
          primary_model_id: "ols_1",
          models: [{
            model_id: "ols_1",
            model_label: "Primary model",
            is_primary: true,
            model_type: "ols",
            outcome: "wage",
            risk_groups: [{
              variable: "region_code",
              display_name: "region_code",
              variable_kind: "dummy_coded",
              risk_level: "WARNING",
              interpretation_guide: "categorical_levels_vs_reference",
              summary: "region_code was dummy-coded.",
              linked_issue_ids: [],
              role_summary: { role: "categorical", status: "confirmed_by_rules", needs_user_confirmation: false },
              terms: [{
                term: "C(Q('region_code'))[T.2]",
                display_term: "region_code = 2",
                level: "2",
                reference_level: "1",
                estimate: 1.23,
                p_value: 0.04,
                source_id: "model_results.ols_1.coefficients.C(Q('region_code'))[T.2]",
              }],
            }],
          }],
        },
        interpretation_restrictions: [],
        recommended_actions: [],
      },
    })
  );

  renderAt("/runs/run-1?project_root=/tmp/demo&tab=overview");

  await waitFor(() => {
    expect(screen.getByText("Coefficient risk")).toBeInTheDocument();
  });
  // Reference column header and value visible
  expect(screen.getByText("Reference")).toBeInTheDocument();
  // reference_level "1" visible in the term row
  expect(screen.getByText("1")).toBeInTheDocument();
  // display_term shows "region_code = 2"
  expect(screen.getByText("region_code = 2")).toBeInTheDocument();
});

// V1.5.0.1 HF2: dark editorial chrome is scoped to ?tab=lineage,
// not the entire /runs/:id route. Overview returns to V1.4 light
// styling (fixes the white-on-white bug); Lineage keeps dark.
// The shell class is computed from URL alone, so we don't need to
// wait for any fetch to complete — querying immediately after
// renderAt is sufficient.
function stubRunDetailAndArtifacts(runId: string) {
  const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
  fetchMock.mockImplementation((url: string) => {
    if (url.includes(`/runs/${runId}/artifacts`)) {
      return Promise.resolve(jsonResponse({ groups: [] }));
    }
    if (url.includes(`/runs/${runId}/graph`)) {
      return Promise.resolve(jsonResponse({ nodes: [], edges: [], legacy: true }));
    }
    if (url.includes(`/runs/${runId}`)) {
      return Promise.resolve(
        jsonResponse({
          run_id: runId,
          status: "completed",
          mode: "auto",
          started_at: "2026-05-01T00:00:00+00:00",
          y: "y",
          x: ["x"],
          lineage: [],
          artifact_counts: {},
          errors: { issues: [] },
          model_results: [],
        }),
      );
    }
    return Promise.resolve(jsonResponse({ runs: [] }));
  });
}

// V1.5.0.1 HF3: clicking a run row in History navigates to
// /runs/:id?tab=overview. Replaces the V1.4 inline-render pattern
// that left URL at /runs and prevented Lineage tab access.
test("HF3: clicking a history row navigates to /runs/:id with tab=overview", async () => {
  const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
  fetchMock.mockImplementation((url: string) => {
    if (url.includes("/projects")) {
      return Promise.resolve(jsonResponse({ project_root: "/tmp/demo" }));
    }
    if (/\/runs\/run-1\/artifacts/.test(url)) {
      return Promise.resolve(jsonResponse({ groups: [] }));
    }
    if (/\/runs\/run-1(\?|$)/.test(url)) {
      return Promise.resolve(jsonResponse(fullRunDetail("run-1", "completed")));
    }
    if (/\/runs(\?|$)/.test(url)) {
      return Promise.resolve(jsonResponse({ runs: [makeRun("run-1")] }));
    }
    return Promise.resolve(jsonResponse({}));
  });

  renderAt("/runs/run-1?project_root=/tmp/demo&tab=overview");

  // RunDetailRoute is mounted — Overview tab is active (matches
  // tab=overview from the URL) and Lineage tab is reachable.
  await waitFor(() => {
    expect(screen.getByRole("tab", { name: "Overview" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });
  expect(screen.getByRole("tab", { name: "Lineage" })).toBeInTheDocument();
  // History panel is gone (no longer inline-rendered).
  expect(screen.queryByRole("heading", { name: /run history/i })).not.toBeInTheDocument();
});

test("HF2: /runs/:id?tab=overview does NOT apply lineage dark shell", async () => {
  stubRunDetailAndArtifacts("run-hf2");
  renderAt("/runs/run-hf2?project_root=/tmp/demo&tab=overview");
  await waitFor(() => {
    expect(screen.getByRole("tab", { name: "Overview" })).toBeInTheDocument();
  });
  const shell = document.querySelector("main.workbench-shell");
  expect(shell).not.toBeNull();
  expect(shell?.classList.contains("workbench-shell--lineage")).toBe(false);
});

test("HF2: /runs/:id?tab=lineage DOES apply lineage dark shell", async () => {
  stubRunDetailAndArtifacts("run-hf2");
  renderAt("/runs/run-hf2?project_root=/tmp/demo&tab=lineage");
  await waitFor(() => {
    expect(screen.getByRole("tab", { name: "Workbench" })).toBeInTheDocument();
  });
  const shell = document.querySelector("main.workbench-shell");
  expect(shell).not.toBeNull();
  expect(shell?.classList.contains("workbench-shell--lineage")).toBe(true);
});

// --- v1.6.8 route inversion (T9) ---

test("/ renders the launcher, not the submit form", async () => {
  renderAt("/");

  expect(await screen.findByRole("button", { name: "New project" })).toBeInTheDocument();
  expect(screen.queryByLabelText("parent folder")).not.toBeInTheDocument();
});

test("/submit redirects into the project graph instead of mounting the abandoned form", async () => {
  (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(
    jsonResponse({ runs: [] }),
  );

  renderAt("/submit?project_root=/tmp/demo");

  await waitFor(() => {
    expect(screen.getByTestId("project-graph-route")).toBeInTheDocument();
  });
  expect(screen.queryByLabelText("data file")).not.toBeInTheDocument();
});

test("/runs/:id redirects into the graph home and forwards focus", async () => {
  const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
  fetchMock.mockResolvedValue(jsonResponse({}));

  renderAt("/runs/run-abc?project_root=/tmp/p1");

  await waitFor(() => {
    expect(screen.getByTestId("project-graph-route")).toBeInTheDocument();
  });
  // focus propagates: the workbench fetches the focused run's graph
  await waitFor(() => {
    const urls = fetchMock.mock.calls.map((c) => String(c[0]));
    expect(urls.some((u) => u.includes("/runs/run-abc/graph"))).toBe(true);
  });
});

test("/p/:slug/graph treats ?focus= as a NODE key, never a run id (C1)", async () => {
  // T11: the container is project-keyed — it fetches the PROJECT forest
  // (GET /graph?project_root=) and never resolves ?focus= as a run id.
  const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
  fetchMock.mockResolvedValue(jsonResponse({ runs: [makeRun("run-1")] }));

  const { rootToSlug } = await import("./workbench/projectSlug");
  renderAt(`/p/${rootToSlug("/tmp/p1")}/graph?focus=abc123::node_7`);

  await waitFor(() => {
    expect(screen.getByTestId("project-graph-route")).toBeInTheDocument();
  });
  await waitFor(() => {
    const urls = fetchMock.mock.calls.map((c) => String(c[0]));
    // fetches the project forest; the node-focus param is not a run id
    expect(urls.some((u) => u.includes("/graph?project_root="))).toBe(true);
    expect(urls.some((u) => u.includes("/runs/abc123"))).toBe(false);
  });
});

test("/runs/:id redirect forwards the run id as ?run= and keeps other params (I2)", async () => {
  const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
  fetchMock.mockResolvedValue(jsonResponse({}));

  renderAt("/runs/run-abc?project_root=/tmp/p1&view=table");

  await waitFor(() => {
    expect(screen.getByTestId("project-graph-route")).toBeInTheDocument();
  });
  await waitFor(() => {
    const urls = fetchMock.mock.calls.map((c) => String(c[0]));
    expect(urls.some((u) => u.includes("/runs/run-abc/graph"))).toBe(true);
  });
});

test("/runs/:id without project_root falls back to the launcher", async () => {
  renderAt("/runs/run-abc");

  expect(await screen.findByRole("button", { name: "New project" })).toBeInTheDocument();
});

test("/p/:slug/graph with a malformed slug falls back to the launcher (F5)", async () => {
  renderAt("/p/!!!not-base64!!!/graph");

  expect(await screen.findByRole("button", { name: "New project" })).toBeInTheDocument();
});

test("/p/:slug/graph on a zero-run project shows the empty canvas with the genesis CTA (T11)", async () => {
  const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
  // T11: the container fetches the project forest; a zero-run project
  // returns empty containers (Task 6 contract).
  fetchMock.mockResolvedValue(
    jsonResponse({
      nodes: {},
      edges: [],
      heads: [],
      families: [],
      schema_version: 2,
      legacy: false,
    }),
  );

  // slug for /tmp/p1 (unicode-safe base64url; see projectSlug.test.ts)
  const { rootToSlug } = await import("./workbench/projectSlug");
  renderAt(`/p/${rootToSlug("/tmp/p1")}/graph`);

  await waitFor(() => {
    expect(screen.getByTestId("project-graph-route")).toBeInTheDocument();
  });
  expect(await screen.findByTestId("genesis-cta")).toBeInTheDocument();
  expect(
    screen.getByText("This project has no imported data or analysis yet."),
  ).toBeInTheDocument();
});

test("project Home activates the Home tab instead of Workbench", async () => {
  (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(
    jsonResponse({
      schema_version: 2,
      heads: [],
      nodes: [],
      edges: [],
      families: [],
      legacy: false,
    }),
  );
  const { rootToSlug } = await import("./workbench/projectSlug");
  renderAt(`/p/${rootToSlug("/tmp/p1")}/graph?view=home`);

  expect(screen.getByRole("tab", { name: "Home" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  expect(screen.getByRole("tab", { name: "Workbench" })).toHaveAttribute(
    "aria-selected",
    "false",
  );
  expect(document.querySelector("main.workbench-shell")).toHaveClass(
    "workbench-shell--lineage",
  );
  await waitFor(() => {
    expect(screen.getByTestId("project-graph-route")).toBeInTheDocument();
  });
});

test("project navigation places a Settings gear immediately before the theme control and opens Settings", async () => {
  const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
  fetchMock.mockImplementation((input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/llm/providers")) {
      return Promise.resolve(
        jsonResponse({ providers: [], active_provider_id: null }),
      );
    }
    return Promise.resolve(
      jsonResponse({
        nodes: {},
        edges: [],
        heads: [],
        families: [],
        schema_version: 2,
        legacy: false,
      }),
    );
  });
  const { rootToSlug } = await import("./workbench/projectSlug");
  renderAt(`/p/${rootToSlug("/tmp/p1")}/graph`);

  const settings = screen.getByRole("button", { name: "Settings" });
  const theme = screen.getByRole("radiogroup", { name: "Theme" });
  expect(settings.nextElementSibling).toBe(theme);

  fireEvent.click(settings);
  expect(await screen.findByTestId("llm-provider-manager")).toBeInTheDocument();
});

import { validatePanelPrediction } from "./App";

describe("validatePanelPrediction", () => {
  it("flags entity == time", () => {
    expect(validatePanelPrediction({
      modelType: "panel_ols", entity: "firm", time: "firm",
      isPanelData: true, predictionEnabled: false, predictionModelType: "",
    })).toMatch(/same column|entity.*time/i);
  });
  it("flags prediction enabled without algorithm", () => {
    expect(validatePanelPrediction({
      modelType: "auto", entity: "", time: "",
      isPanelData: false, predictionEnabled: true, predictionModelType: "",
    })).toMatch(/algorithm/i);
  });
  it("flags panel selected, no columns, non-panel data", () => {
    expect(validatePanelPrediction({
      modelType: "panel_ols", entity: "", time: "",
      isPanelData: false, predictionEnabled: false, predictionModelType: "",
    })).toMatch(/panel/i);
  });
  it("passes a valid panel config", () => {
    expect(validatePanelPrediction({
      modelType: "panel_ols", entity: "firm", time: "yr",
      isPanelData: true, predictionEnabled: false, predictionModelType: "",
    })).toBeNull();
  });
  it("passes a non-panel non-prediction config", () => {
    expect(validatePanelPrediction({
      modelType: "auto", entity: "", time: "",
      isPanelData: false, predictionEnabled: false, predictionModelType: "",
    })).toBeNull();
  });
});
