import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
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
});

afterEach(() => {
  vi.unstubAllGlobals();
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

test("runWorkflow shows run result inline on submit page", async () => {
  const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
  fetchMock.mockResolvedValueOnce(jsonResponse({ project_root: "/tmp/demo" }));
  // POST returns running (async)
  fetchMock.mockResolvedValueOnce(
    jsonResponse({ run_id: "abc-123", status: "running" })
  );
  // GET run detail
  fetchMock.mockResolvedValueOnce(
    jsonResponse({
      run_id: "abc-123", status: "completed", mode: "auto",
      started_at: "2026-05-01T00:00:00+00:00", y: "y", x: ["x1", "x2"],
      lineage: [], artifact_counts: { report: 1 }, errors: { issues: [] },
      model_results: [
        {
          model_id: "ols_1",
          r_squared: 0.9,
          coefficients: {
            x1: { estimate: 2, std_error: 0.1, p_value: 0.01 },
          },
        },
      ],
    })
  );
  // GET run artifacts
  fetchMock.mockResolvedValueOnce(jsonResponse({ groups: [] }));

  renderAt("/");
  await fillProject();
  fillRunForm();
  fireEvent.click(screen.getByRole("button", { name: "Run workflow" }));

  await waitFor(() => {
    expect(
      screen.getByRole("heading", { name: /run detail/i })
    ).toBeInTheDocument();
  });
  expect(screen.getByRole("heading", { name: "Project" })).toBeInTheDocument();
  expect(screen.getByText("abc-123")).toBeInTheDocument();
  expect(screen.getAllByText("Completed").length).toBeGreaterThan(0);
  expect(screen.getByRole("heading", { name: /coefficients/i })).toBeInTheDocument();
  expect(document.body).toHaveTextContent("ols_1");
  expect(document.body).toHaveTextContent("x1");
});

test("runWorkflow blocked shows run result inline with blocked status", async () => {
  const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
  fetchMock.mockResolvedValueOnce(jsonResponse({ project_root: "/tmp/demo" }));
  // POST returns running (workflow is async, blocked result comes later)
  fetchMock.mockResolvedValueOnce(
    jsonResponse({ run_id: "blk-1", status: "running" })
  );
  // GET run detail shows blocked
  fetchMock.mockResolvedValueOnce(
    jsonResponse({
      run_id: "blk-1", status: "blocked", mode: "auto",
      started_at: "2026-05-01T00:00:00+00:00", y: "y", x: ["x1", "x2"],
      lineage: [], artifact_counts: {}, errors: {
        issues: [{ severity: "BLOCKER", code: "DATA_QUALITY", message: "Bad data" }],
      },
    })
  );
  // GET artifacts
  fetchMock.mockResolvedValueOnce(jsonResponse({ groups: [] }));

  renderAt("/");
  await fillProject();
  fillRunForm();
  fireEvent.click(screen.getByRole("button", { name: "Run workflow" }));

  await waitFor(() => {
    expect(
      screen.getByRole("heading", { name: /run detail/i })
    ).toBeInTheDocument();
  });
  expect(screen.getByRole("heading", { name: "Project" })).toBeInTheDocument();
  expect(screen.getByText("blk-1")).toBeInTheDocument();
  expect(screen.getAllByText("Blocked").length).toBeGreaterThan(0);
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
  expect(screen.getByRole("heading", { name: /run history/i })).toBeInTheDocument();
  expect(screen.getByText("Bad column")).toBeInTheDocument();
  expect(screen.getByText("DATA_QUALITY")).toBeInTheDocument();
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
    "/runs/run-1/artifacts/report_html?project_root=%2Ftmp%2Fdemo",
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
    "/runs/run-1/report?project_root=%2Ftmp%2Fdemo",
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

test("model type selector renders with auto, ols, logit, poisson options", () => {
  renderAt("/");

  const selector = screen.getByLabelText("model type");
  expect(selector).toBeInTheDocument();

  const options = within(selector).getAllByRole("option");
  const optionValues = options.map((opt) => (opt as HTMLOptionElement).value);
  expect(optionValues).toEqual(["auto", "ols", "logit", "poisson"]);
});

test("model type defaults to Auto and can be changed to logit", async () => {
  renderAt("/");

  const selector = screen.getByLabelText("model type") as HTMLSelectElement;
  expect(selector.value).toBe("auto");

  fireEvent.change(selector, { target: { value: "logit" } });
  expect(selector.value).toBe("logit");
});
