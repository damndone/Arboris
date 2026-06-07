import "@testing-library/jest-dom/vitest";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
import * as XLSX from "xlsx";

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
    // V1.5.0.1 HF4: lastRun is persisted in sessionStorage; clear
    // it between tests so a previous test's run cannot leak into the
    // next test's SubmitRoute mount.
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

async function fillProject(parent = "/tmp"): Promise<void> {
  fireEvent.change(screen.getByLabelText("parent folder"), {
    target: { value: parent }
  });
  fireEvent.click(screen.getByRole("button", { name: "Create project" }));
  await waitFor(() => {
    expect(screen.getByText(`${parent}/demo`)).toBeInTheDocument();
  });
}

function fillRunForm(): void {
  fireEvent.change(screen.getByLabelText("dependent variable"), {
    target: { value: "y" }
  });
  fireEvent.change(screen.getByLabelText("independent variables"), {
    target: { value: "x1, x2" }
  });
  const file = new File(["a,b\n1,2\n"], "data.csv", { type: "text/csv" });
  fireEvent.change(screen.getByLabelText("data file"), {
    target: { files: [file] }
  });
}

function makeXlsxFile(): File {
  const sheet = XLSX.utils.json_to_sheet([
    { target: 10, x1: 1, x2: 100, user_id: "u1" },
    { target: 12, x1: 2, x2: 120, user_id: "u2" },
    { target: 14, x1: 3, x2: 140, user_id: "u3" },
  ]);
  const workbook = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(workbook, sheet, "Data");
  const data = XLSX.write(workbook, { bookType: "xlsx", type: "array" });
  return new File([data], "data.xlsx", {
    type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  });
}

test("renders workbench panels and disables run when invalid", () => {
  renderAt("/");

  expect(
    screen.getByRole("heading", { name: "Local Econometrics Workbench" })
  ).toBeInTheDocument();
  expect(screen.getByLabelText("parent folder")).toBeInTheDocument();
  expect(screen.getByLabelText("project name")).toBeInTheDocument();
  expect(screen.getByLabelText("run mode")).toBeInTheDocument();
  expect(screen.getByLabelText("dependent variable")).toBeInTheDocument();
  expect(screen.getByLabelText("independent variables")).toBeInTheDocument();
  expect(screen.getByLabelText("data file")).toBeInTheDocument();

  expect(screen.getByRole("button", { name: "Create project" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Run workflow" })).toBeDisabled();

  expect(screen.getByRole("heading", { name: /last run/i })).toBeInTheDocument();
  expect(screen.getByText(/no run yet/i)).toBeInTheDocument();
});

test("selecting an XLSX file previews rows and applies suggested variables", async () => {
  renderAt("/");

  fireEvent.change(screen.getByLabelText("data file"), {
    target: { files: [makeXlsxFile()] },
  });

  await waitFor(() => {
    expect(screen.getByRole("heading", { name: /data preview/i })).toBeInTheDocument();
  });

  expect(document.body).toHaveTextContent("data.xlsx");
  expect(document.body).toHaveTextContent("3 rows");
  expect(document.body).toHaveTextContent("4 columns");
  expect(screen.getAllByText("target").length).toBeGreaterThan(0);
  expect(screen.getByLabelText("dependent variable")).toHaveValue("target");
  expect(screen.getByLabelText("independent variables")).toHaveValue("x1, x2");
});

test("createProject success populates project_root", async () => {
  (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
    jsonResponse({ project_root: "/tmp/demo" })
  );

  renderAt("/");
  await fillProject();

  expect(screen.getByText("/tmp/demo")).toBeInTheDocument();
});

// V1.5.0.1 HF1: after a successful run, the Submit page stays on /
// and renders the V1.4 result summary inline. The "Open Lineage →"
// button on the Last run heading is the explicit user gesture that
// navigates to the dark lineage view. The V1.5.0 P0 forced auto-nav
// was removed because users lost sight of the result they just ran
// and were jarred by the light → dark flip.
function minimalGraphResponse(runId: string) {
  return {
    schema_version: 3,
    run_id: runId,
    legacy: false,
    stats: { node_count: 0, edge_count: 0, leaf_count: 0, has_dp_count: 0 },
    nodes: {},
    edges: {},
    branches: {},
  };
}

// Route mocked fetches by URL so the polling-aware flow (POST → poll
// runDetail → GET graph) doesn't have to be encoded as a fragile
// sequential chain.
type RouteFn = (url: string, init?: RequestInit) => Response | Promise<Response>;
function installFetchRouter(fetchMock: ReturnType<typeof vi.fn>, route: RouteFn) {
  fetchMock.mockImplementation((url, init) => {
    const u = typeof url === "string" ? url : String(url);
    return Promise.resolve(route(u, init));
  });
}

// RunResultView reads several optional fields (errors.issues,
// artifact_counts, lineage, model_results). When the Submit route is
// rendered mid-poll the inline RunResultView crashes if these are
// missing, even though the test only cares about the navigation
// contract. Build a fully-populated minimal RunDetail so the inline
// render doesn't blow up while we wait for polling to complete.
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

test("runWorkflow polls until terminal then stays on Submit with Open Lineage button [HF1]", async () => {
  // V1.5.0.1 HF1: do NOT auto-navigate after a run completes. The
  // run-detail polling still gates against the orchestrator's
  // background race, but the user stays on Submit and sees the
  // V1.4 result summary inline. An "Open Lineage →" button on the
  // Last run heading is the explicit gesture for entering lineage.
  // Use POST /runs that returns "completed" directly (no polling)
  // to keep the test deterministic; the polling gate is exercised
  // by api.test.ts waitForRunTerminal suite. This test focuses on
  // the post-run UI contract.
  const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
  installFetchRouter(fetchMock, (url) => {
    if (url.includes("/projects"))
      return jsonResponse({ project_root: "/tmp/demo" });
    if (/\/runs\/abc-123\/artifacts(\?|$)/.test(url)) {
      return jsonResponse({ groups: [] });
    }
    if (/\/runs\/abc-123(\?|$)/.test(url)) {
      return jsonResponse(fullRunDetail("abc-123", "completed"));
    }
    if (/\/runs(\?|$)/.test(url)) {
      return jsonResponse({ run_id: "abc-123", status: "completed" });
    }
    return jsonResponse({});
  });

  renderAt("/");
  await fillProject();
  fillRunForm();
  fireEvent.click(screen.getByRole("button", { name: "Run workflow" }));

  // After the run terminates, the Submit tab stays selected and the
  // Open Lineage button appears on the Last run heading.
  await waitFor(() => {
    expect(
      screen.getByRole("button", { name: /Open Lineage/ }),
    ).toBeInTheDocument();
  });
  // Submit tab still active, NOT Lineage.
  expect(
    screen.getByRole("tab", { name: "Submit" }),
  ).toHaveAttribute("aria-selected", "true");
});

test("Open Lineage button navigates to /runs/:id?tab=lineage [HF1]", async () => {
  const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
  installFetchRouter(fetchMock, (url) => {
    if (url.includes("/projects")) {
      return jsonResponse({ project_root: "/tmp/demo" });
    }
    if (/\/runs\/blk-1\/graph(\?|$)/.test(url)) {
      return jsonResponse(minimalGraphResponse("blk-1"));
    }
    if (/\/runs\/blk-1\/artifacts(\?|$)/.test(url)) {
      return jsonResponse({ groups: [] });
    }
    if (/\/runs\/blk-1(\?|$)/.test(url)) {
      return jsonResponse(fullRunDetail("blk-1", "blocked"));
    }
    if (/\/runs(\?|$)/.test(url)) {
      // A run that lands as blocked from the POST itself has finished
      // — no polling needed. The button still appears and lets the
      // user enter the lineage view if they want to inspect.
      return jsonResponse({ run_id: "blk-1", status: "blocked" });
    }
    return jsonResponse({});
  });

  renderAt("/");
  await fillProject();
  fillRunForm();
  fireEvent.click(screen.getByRole("button", { name: "Run workflow" }));

  // Wait for the Open Lineage button to appear (run terminated).
  const openBtn = await waitFor(
    () => screen.getByRole("button", { name: /Open Lineage/ }),
    { timeout: 4000 },
  );
  fireEvent.click(openBtn);

  // After the explicit click, the Lineage tab is selected.
  await waitFor(() => {
    expect(
      screen.getByRole("tab", { name: "Lineage" }),
    ).toHaveAttribute("aria-selected", "true");
  });
});

test("V1.5.1 T1.3 — Submit shows live step progress from SSE step_start", async () => {
  // SSE happy path: POST /runs returns running so waitForRunTerminal
  // takes the SSE subscribe path. A stubbed EventSource lets us fire
  // a step_start event mid-run; the Submit page should render the
  // step text in the └─ progress chip.
  class MockEventSource {
    static instances: MockEventSource[] = [];
    url: string;
    listeners = new Map<string, ((e: MessageEvent) => void)[]>();
    onerror: ((e: Event) => void) | null = null;
    close = vi.fn();
    constructor(url: string) {
      this.url = url;
      MockEventSource.instances.push(this);
    }
    addEventListener(type: string, fn: (e: MessageEvent) => void) {
      const list = this.listeners.get(type) ?? [];
      list.push(fn);
      this.listeners.set(type, list);
    }
    fire(type: string, data: unknown) {
      for (const fn of this.listeners.get(type) ?? []) {
        fn({ data: JSON.stringify(data) } as MessageEvent);
      }
    }
  }
  MockEventSource.instances = [];
  vi.stubGlobal("EventSource", MockEventSource);

  const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
  installFetchRouter(fetchMock, (url) => {
    if (url.includes("/projects"))
      return jsonResponse({ project_root: "/tmp/demo" });
    if (/\/runs\/run-sse\/artifacts(\?|$)/.test(url)) {
      return jsonResponse({ groups: [] });
    }
    if (/\/runs\/run-sse(\?|$)/.test(url)) {
      return jsonResponse(fullRunDetail("run-sse", "completed"));
    }
    if (/\/runs(\?|$)/.test(url)) {
      return jsonResponse({ run_id: "run-sse", status: "running" });
    }
    return jsonResponse({});
  });

  renderAt("/");
  await fillProject();
  fillRunForm();
  fireEvent.click(screen.getByRole("button", { name: "Run workflow" }));

  // EventSource is opened inside the SSE subscribe path; wait for it
  // before firing simulated server events.
  await waitFor(() => {
    expect(MockEventSource.instances.length).toBeGreaterThan(0);
  });
  const source = MockEventSource.instances.at(-1)!;
  act(() => {
    source.fire("step_start", {
      event: "step_start",
      run_id: "run-sse",
      sequence: 1,
      timestamp: "2026-05-01T00:00:01+00:00",
      step: "regress",
      message: "Running OLS",
      status: null,
    });
  });

  await waitFor(() => {
    expect(screen.getByTestId("run-progress-line")).toHaveTextContent(
      /regress: Running OLS/,
    );
  });

  // Fire terminal so waitForRunTerminal resolves and the test doesn't
  // dangle on a pending promise.
  act(() => {
    source.fire("workflow_completed", {
      event: "workflow_completed",
      run_id: "run-sse",
      sequence: 2,
      timestamp: "2026-05-01T00:00:05+00:00",
      step: null,
      message: "Done",
      status: "completed",
    });
  });
  await waitFor(() => {
    expect(
      screen.getByRole("button", { name: /Open Lineage/ }),
    ).toBeInTheDocument();
  });
  // Progress chip clears once the run terminates.
  expect(screen.queryByTestId("run-progress-line")).not.toBeInTheDocument();
});

test("HTTP 413 surfaces FastAPI string detail in error panel", async () => {
  const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
  fetchMock.mockResolvedValueOnce(jsonResponse({ project_root: "/tmp/demo" }));
  fetchMock.mockResolvedValueOnce(
    jsonResponse(
      { detail: "Uploaded file exceeds project size limit." },
      { status: 413 }
    )
  );

  renderAt("/");
  await fillProject();
  fillRunForm();
  fireEvent.click(screen.getByRole("button", { name: "Run workflow" }));

  await waitFor(() => {
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });

  const alert = screen.getByRole("alert");
  expect(alert).toHaveTextContent("HTTP 413");
  expect(alert).toHaveTextContent("Uploaded file exceeds project size limit.");
});

test("HTTP 422 with validation array detail joins location + msg", async () => {
  const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
  fetchMock.mockResolvedValueOnce(
    jsonResponse(
      {
        detail: [
          { loc: ["body", "parent"], msg: "field required", type: "value_error" }
        ]
      },
      { status: 422 }
    )
  );

  renderAt("/");
  fireEvent.change(screen.getByLabelText("parent folder"), {
    target: { value: "/tmp" }
  });
  fireEvent.click(screen.getByRole("button", { name: "Create project" }));

  await waitFor(() => {
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });

  const alert = screen.getByRole("alert");
  expect(alert).toHaveTextContent("HTTP 422");
  expect(alert).toHaveTextContent("parent: field required");
});

test("history tab fetches and lists runs for the current project", async () => {
  const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
  fetchMock.mockResolvedValueOnce(jsonResponse({ project_root: "/tmp/demo" }));
  fetchMock.mockResolvedValueOnce(
    jsonResponse({
      runs: [
        makeRun("run-2", { status: "completed" }),
        makeRun("run-1", { status: "blocked" }),
      ],
    })
  );

  renderAt("/");
  await fillProject();

  fireEvent.click(screen.getByRole("tab", { name: "History" }));

  await waitFor(() => {
    expect(screen.getByText("run-1")).toBeInTheDocument();
  });
  expect(screen.getByText("run-2")).toBeInTheDocument();
  expect(screen.getByText("Blocked")).toBeInTheDocument();
});

test("clicking a history row loads run detail with errors", async () => {
  const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
  fetchMock.mockResolvedValueOnce(jsonResponse({ project_root: "/tmp/demo" }));
  fetchMock.mockResolvedValueOnce(
    jsonResponse({
      runs: [makeRun("run-1", { status: "blocked" })],
    })
  );
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

  renderAt("/");
  await fillProject();
  fireEvent.click(screen.getByRole("tab", { name: "History" }));
  await waitFor(() => screen.getByText("run-1"));

  fireEvent.click(screen.getByText("run-1"));

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
  fetchMock.mockResolvedValueOnce(jsonResponse({ project_root: "/tmp/demo" }));
  fetchMock.mockResolvedValueOnce(
    jsonResponse({
      runs: [makeRun("run-1")],
    })
  );
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

  renderAt("/");
  await fillProject();
  fireEvent.click(screen.getByRole("tab", { name: "History" }));
  await waitFor(() => screen.getByText("run-1"));

  fireEvent.click(screen.getByText("run-1"));

  await waitFor(() => {
    expect(screen.getByText("CATEGORICAL_CANDIDATE")).toBeInTheDocument();
  });
  expect(screen.queryByText("Issues")).not.toBeInTheDocument();
  expect(screen.getByText("System notes")).toBeInTheDocument();
});

test("run detail normalizes stale categorical candidate when model dummy-coded it", async () => {
  const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
  fetchMock.mockResolvedValueOnce(jsonResponse({ project_root: "/tmp/demo" }));
  fetchMock.mockResolvedValueOnce(
    jsonResponse({
      runs: [makeRun("run-1")],
    })
  );
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

  renderAt("/");
  await fillProject();
  fireEvent.click(screen.getByRole("tab", { name: "History" }));
  await waitFor(() => screen.getByText("run-1"));

  fireEvent.click(screen.getByText("run-1"));

  await waitFor(() => {
    expect(screen.getByText("CATEGORICAL_AUTO_DUMMY_CODED")).toBeInTheDocument();
  });
  expect(screen.queryByText("CATEGORICAL_CANDIDATE")).not.toBeInTheDocument();
  expect(screen.queryByText(/Consider one-hot encoding/)).not.toBeInTheDocument();
});

test("run detail renders warning issues separately from blockers", async () => {
  const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
  fetchMock.mockResolvedValueOnce(jsonResponse({ project_root: "/tmp/demo" }));
  fetchMock.mockResolvedValueOnce(
    jsonResponse({
      runs: [makeRun("run-1")],
    })
  );
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

  renderAt("/");
  await fillProject();
  fireEvent.click(screen.getByRole("tab", { name: "History" }));
  await waitFor(() => screen.getByText("run-1"));

  fireEvent.click(screen.getByText("run-1"));

  await waitFor(() => {
    expect(screen.getByText("TREATMENT_PROXY_CORRELATION")).toBeInTheDocument();
  });
  expect(screen.queryByText("Issues")).not.toBeInTheDocument();
  expect(screen.getByText("Warnings")).toBeInTheDocument();
});

test("history tab surfaces PROJECT_NOT_FOUND envelope in error panel", async () => {
  const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
  fetchMock.mockResolvedValueOnce(jsonResponse({ project_root: "/tmp/demo" }));
  fetchMock.mockResolvedValueOnce(
    jsonResponse(
      {
        error: {
          code: "PROJECT_NOT_FOUND",
          message: "Project not found",
          details: {},
        },
      },
      { status: 404 }
    )
  );

  renderAt("/");
  await fillProject();
  fireEvent.click(screen.getByRole("tab", { name: "History" }));

  await waitFor(() => {
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });
  expect(screen.getByRole("alert")).toHaveTextContent("PROJECT_NOT_FOUND");
});

test("run detail shows artifact list with download links", async () => {
  const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
  fetchMock.mockResolvedValueOnce(jsonResponse({ project_root: "/tmp/demo" }));
  fetchMock.mockResolvedValueOnce(
    jsonResponse({
      runs: [makeRun("run-1")],
    })
  );
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

  renderAt("/");
  await fillProject();
  fireEvent.click(screen.getByRole("tab", { name: "History" }));
  await waitFor(() => screen.getByText("run-1"));
  fireEvent.click(screen.getByText("run-1"));

  await waitFor(() => screen.getByRole("heading", { name: /artifacts/i }));

  const downloadLink = screen.getByRole("link", { name: /report_html/i });
  expect(downloadLink).toHaveAttribute(
    "href",
    "/api/runs/run-1/artifacts/report_html?project_root=%2Ftmp%2Fdemo",
  );
});

test("view report toggles iframe with report URL", async () => {
  const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
  fetchMock.mockResolvedValueOnce(jsonResponse({ project_root: "/tmp/demo" }));
  fetchMock.mockResolvedValueOnce(
    jsonResponse({ runs: [makeRun("run-1")] })
  );
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

  renderAt("/");
  await fillProject();
  fireEvent.click(screen.getByRole("tab", { name: "History" }));
  await waitFor(() => screen.getByText("run-1"));
  fireEvent.click(screen.getByText("run-1"));

  await waitFor(() => screen.getByRole("button", { name: /view report/i }));
  fireEvent.click(screen.getByRole("button", { name: /view report/i }));

  const iframe = screen.getByTitle("Run report") as HTMLIFrameElement;
  expect(iframe.src).toContain(
    "/api/runs/run-1/report?project_root=%2Ftmp%2Fdemo",
  );
});

test("report iframe has sandbox attribute restricting scripts", async () => {
  const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
  fetchMock.mockResolvedValueOnce(jsonResponse({ project_root: "/tmp/demo" }));
  fetchMock.mockResolvedValueOnce(
    jsonResponse({ runs: [makeRun("run-1")] })
  );
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

  renderAt("/");
  await fillProject();
  fireEvent.click(screen.getByRole("tab", { name: "History" }));
  await waitFor(() => screen.getByText("run-1"));
  fireEvent.click(screen.getByText("run-1"));

  await waitFor(() => screen.getByRole("button", { name: /view report/i }));
  fireEvent.click(screen.getByRole("button", { name: /view report/i }));

  const iframe = screen.getByTitle("Run report") as HTMLIFrameElement;
  expect(iframe.getAttribute("sandbox")).toBe("allow-same-origin");
});

test("artifact fetch error shows retry button; retry succeeds", async () => {
  const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;

  fetchMock.mockResolvedValueOnce(jsonResponse({ project_root: "/tmp/demo" }));
  fetchMock.mockResolvedValueOnce(
    jsonResponse({
      runs: [makeRun("run-1")],
    })
  );
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

  renderAt("/");
  await fillProject();
  fireEvent.click(screen.getByRole("tab", { name: "History" }));
  await waitFor(() => screen.getByText("run-1"));
  fireEvent.click(screen.getByText("run-1"));

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

test("direct URL access to history via MemoryRouter initialEntries renders runs", async () => {
  const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
  fetchMock.mockResolvedValueOnce(
    jsonResponse({ runs: [makeRun("run-direct")] })
  );

  renderAt("/runs?project_root=/tmp");

  await waitFor(() => {
    expect(screen.getByRole("heading", { name: /run history/i })).toBeInTheDocument();
  });
  expect(screen.getByText("run-direct")).toBeInTheDocument();
  expect(screen.getByText("Completed")).toBeInTheDocument();
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

  renderAt("/runs/run-direct?project_root=/tmp/demo");

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

  renderAt("/runs/run-direct?project_root=/tmp/demo");

  await waitFor(() => {
    expect(screen.getByRole("heading", { name: /coefficients/i })).toBeInTheDocument();
  });
  expect(screen.getByText("< 0.001")).toBeInTheDocument();
  expect(document.body).not.toHaveTextContent("0.0000");
});

test("history pagination bar renders Page X of Y, Previous disabled on first page", async () => {
  const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
  fetchMock.mockResolvedValueOnce(jsonResponse({ project_root: "/tmp/demo" }));
  // 30 runs → PAGE_SIZE=25 → 2 pages
  fetchMock.mockResolvedValueOnce(
    jsonResponse({ runs: makeRuns(30) })
  );

  renderAt("/");
  await fillProject();
  fireEvent.click(screen.getByRole("tab", { name: "History" }));

  await waitFor(() => {
    expect(screen.getByText("run-1")).toBeInTheDocument();
  });

  const pagination = screen.getByLabelText("run history pagination");
  expect(within(pagination).getByText("Page 1 of 2")).toBeInTheDocument();
  expect(within(pagination).getByRole("button", { name: "Previous" })).toBeDisabled();
  expect(within(pagination).getByRole("button", { name: "Next" })).toBeEnabled();

  // Navigate to page 2
  fireEvent.click(within(pagination).getByRole("button", { name: "Next" }));

  await waitFor(() => {
    expect(within(pagination).getByText("Page 2 of 2")).toBeInTheDocument();
  });
  expect(within(pagination).getByRole("button", { name: "Previous" })).toBeEnabled();
  expect(within(pagination).getByRole("button", { name: "Next" })).toBeDisabled();

  // run-26 should be on page 2
  expect(screen.getByText("run-26")).toBeInTheDocument();
  // run-1 should NOT be on page 2
  expect(screen.queryByText("run-1")).not.toBeInTheDocument();
});

test("empty run list does not render pagination bar", async () => {
  const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
  fetchMock.mockResolvedValueOnce(jsonResponse({ project_root: "/tmp/demo" }));
  fetchMock.mockResolvedValueOnce(
    jsonResponse({ runs: [] })
  );

  renderAt("/");
  await fillProject();
  fireEvent.click(screen.getByRole("tab", { name: "History" }));

  await waitFor(() => {
    expect(screen.getByText(/no runs in this project yet/i)).toBeInTheDocument();
  });

  expect(
    screen.queryByLabelText("run history pagination")
  ).not.toBeInTheDocument();
});

test("/runs route with missing project_root shows prompt", () => {
  renderAt("/runs");

  expect(screen.getByText(/select a project first/i)).toBeInTheDocument();
  expect(
    screen.queryByLabelText("run history")
  ).not.toBeInTheDocument();
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

  renderAt("/runs/running-1?project_root=/tmp/demo");

  await waitFor(() => {
    expect(screen.getByLabelText("run progress")).toBeInTheDocument();
  });
  expect(screen.getByText("Statistical tests")).toBeInTheDocument();
});

// --- V1.2.5 model type selector tests ---

test("model type selector renders options from capabilities", () => {
  renderAt("/");

  const selector = screen.getByLabelText("model type");
  expect(selector).toBeInTheDocument();

  const options = within(selector).getAllByRole("option");
  const optionValues = options.map((opt) => (opt as HTMLOptionElement).value);
  expect(optionValues).toEqual([
    "auto",
    "ols",
    "logit",
    "poisson",
    "negative_binomial",
  ]);
  expect(
    within(selector).getByRole("option", { name: "OLS (linear)" }),
  ).toHaveValue("ols");
});

test("model type defaults to Auto and can be changed to logit", async () => {
  renderAt("/");

  const selector = screen.getByLabelText("model type") as HTMLSelectElement;
  expect(selector.value).toBe("auto");

  fireEvent.change(selector, { target: { value: "logit" } });
  expect(selector.value).toBe("logit");
});

// --- V1.3.1 Trust Preview regression tests ---

test("report is disabled when artifact manifest is missing in preview", async () => {
  const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
  fetchMock.mockResolvedValueOnce(jsonResponse({ project_root: "/tmp/demo" }));
  fetchMock.mockResolvedValueOnce(
    jsonResponse({ runs: [makeRun("run-1")] })
  );
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

  renderAt("/");
  await fillProject();
  fireEvent.click(screen.getByRole("tab", { name: "History" }));
  await waitFor(() => screen.getByText("run-1"));
  fireEvent.click(screen.getByText("run-1"));

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
  fetchMock.mockResolvedValueOnce(jsonResponse({ project_root: "/tmp/demo" }));
  fetchMock.mockResolvedValueOnce(
    jsonResponse({ runs: [makeRun("run-1")] })
  );
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

  renderAt("/");
  await fillProject();
  fireEvent.click(screen.getByRole("tab", { name: "History" }));
  await waitFor(() => screen.getByText("run-1"));
  fireEvent.click(screen.getByText("run-1"));

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

  renderAt("/");
  await fillProject();
  fireEvent.click(screen.getByRole("tab", { name: "History" }));
  await waitFor(() => screen.getByText("run-1"));

  fireEvent.click(screen.getByText("run-1"));

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

test("HF2: /runs/:id?tab=overview does NOT apply lineage dark shell", () => {
  stubRunDetailAndArtifacts("run-hf2");
  renderAt("/runs/run-hf2?project_root=/tmp/demo&tab=overview");
  const shell = document.querySelector("main.workbench-shell");
  expect(shell).not.toBeNull();
  expect(shell?.classList.contains("workbench-shell--lineage")).toBe(false);
});

// V1.5.0.1 HF4: lastRun survives SubmitRoute remount via sessionStorage.
// Before this fix it was plain useState and was discarded on navigation.
test("HF4: lastRun persisted in sessionStorage survives SubmitRoute remount", async () => {
  // Seed sessionStorage as if a previous session had completed run-prev.
  sessionStorage.setItem(
    "workbench:lastRun",
    JSON.stringify({ run_id: "run-prev", status: "completed" }),
  );

  const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
  fetchMock.mockImplementation((url: string) => {
    if (url.includes("/projects")) {
      return Promise.resolve(jsonResponse({ project_root: "/tmp/demo" }));
    }
    if (/\/runs\/run-prev\/artifacts/.test(url)) {
      return Promise.resolve(jsonResponse({ groups: [] }));
    }
    if (/\/runs\/run-prev(\?|$)/.test(url)) {
      return Promise.resolve(jsonResponse(fullRunDetail("run-prev", "completed")));
    }
    return Promise.resolve(jsonResponse({}));
  });

  renderAt("/");

  // Without HF4, lastRun starts as null and Open Lineage doesn't render.
  // With HF4, the seeded value is restored and the button appears.
  await waitFor(() => {
    expect(
      screen.getByRole("button", { name: /Open Lineage/ }),
    ).toBeInTheDocument();
  });
});

test("HF2: /runs/:id?tab=lineage DOES apply lineage dark shell", () => {
  stubRunDetailAndArtifacts("run-hf2");
  renderAt("/runs/run-hf2?project_root=/tmp/demo&tab=lineage");
  const shell = document.querySelector("main.workbench-shell");
  expect(shell).not.toBeNull();
  expect(shell?.classList.contains("workbench-shell--lineage")).toBe(true);
});

import { validatePanelPrediction } from "./App";

describe("validatePanelPrediction", () => {
  it("flags entity == time", () => {
    expect(validatePanelPrediction({
      modelType: "panel_ols", entity: "firm", time: "firm",
      isPanelData: true, predictionEnabled: false, predictionModelType: "",
    })).toMatch(/相同|同一列|entity.*time/i);
  });
  it("flags prediction enabled without algorithm", () => {
    expect(validatePanelPrediction({
      modelType: "auto", entity: "", time: "",
      isPanelData: false, predictionEnabled: true, predictionModelType: "",
    })).toMatch(/算法|algorithm/i);
  });
  it("flags panel selected, no columns, non-panel data", () => {
    expect(validatePanelPrediction({
      modelType: "panel_ols", entity: "", time: "",
      isPanelData: false, predictionEnabled: false, predictionModelType: "",
    })).toMatch(/面板|panel/i);
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
