import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import App from "./App";

type FetchInit = { status?: number; ok?: boolean };

function jsonResponse(body: unknown, init: FetchInit = {}): Response {
  const status = init.status ?? 200;
  return {
    ok: init.ok ?? (status >= 200 && status < 300),
    status,
    json: () => Promise.resolve(body)
  } as unknown as Response;
}

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn());
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

test("renders workbench panels and disables run when invalid", () => {
  render(<App />);

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

test("createProject success populates project_root", async () => {
  (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
    jsonResponse({ project_root: "/tmp/demo" })
  );

  render(<App />);
  await fillProject();

  expect(screen.getByText("/tmp/demo")).toBeInTheDocument();
});

test("runWorkflow completed shows run_id, badge and expected output paths", async () => {
  const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
  fetchMock.mockResolvedValueOnce(jsonResponse({ project_root: "/tmp/demo" }));
  fetchMock.mockResolvedValueOnce(
    jsonResponse({ run_id: "abc-123", status: "completed" })
  );

  render(<App />);
  await fillProject();
  fillRunForm();
  fireEvent.click(screen.getByRole("button", { name: "Run workflow" }));

  await waitFor(() => {
    expect(screen.getByText("abc-123")).toBeInTheDocument();
  });

  expect(screen.getByText("Completed")).toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();

  const outputs = screen.getByLabelText("expected outputs");
  expect(
    within(outputs).getByText("/tmp/demo/runs/abc-123/run_manifest.json")
  ).toBeInTheDocument();
  expect(
    within(outputs).getByText("/tmp/demo/runs/abc-123/artifacts_index.json")
  ).toBeInTheDocument();
  expect(
    within(outputs).getByText("/tmp/demo/runs/abc-123/errors.json")
  ).toBeInTheDocument();
  expect(
    within(outputs).getByText("/tmp/demo/runs/abc-123/reports/report.html")
  ).toBeInTheDocument();
  expect(
    within(outputs).getByText("/tmp/demo/runs/abc-123/reports/report.pdf")
  ).toBeInTheDocument();
  expect(
    within(outputs).getByText("/tmp/demo/runs/abc-123/exports/tables.xlsx")
  ).toBeInTheDocument();
});

test("runWorkflow blocked is workflow status, not an HTTP error", async () => {
  const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
  fetchMock.mockResolvedValueOnce(jsonResponse({ project_root: "/tmp/demo" }));
  fetchMock.mockResolvedValueOnce(
    jsonResponse({ run_id: "blk-1", status: "blocked" })
  );

  render(<App />);
  await fillProject();
  fillRunForm();
  fireEvent.click(screen.getByRole("button", { name: "Run workflow" }));

  await waitFor(() => {
    expect(screen.getByText("blk-1")).toBeInTheDocument();
  });

  expect(screen.getByText("Blocked")).toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(screen.getByText(/inspect/i)).toBeInTheDocument();
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

  render(<App />);
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

  render(<App />);
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
        {
          run_id: "run-2",
          status: "completed",
          mode: "auto",
          started_at: "2026-05-01T01:00:00+00:00",
          y: "y",
          x: ["x"],
        },
        {
          run_id: "run-1",
          status: "blocked",
          mode: "auto",
          started_at: "2026-05-01T00:00:00+00:00",
          y: "y",
          x: ["x"],
        },
      ],
    })
  );

  render(<App />);
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
      runs: [
        {
          run_id: "run-1",
          status: "blocked",
          mode: "auto",
          started_at: "2026-05-01T00:00:00+00:00",
          y: "y",
          x: ["x"],
        },
      ],
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

  render(<App />);
  await fillProject();
  fireEvent.click(screen.getByRole("tab", { name: "History" }));
  await waitFor(() => screen.getByText("run-1"));

  fireEvent.click(screen.getByText("run-1"));

  await waitFor(() => {
    expect(
      screen.getByRole("heading", { name: /run detail/i })
    ).toBeInTheDocument();
  });
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

  render(<App />);
  await fillProject();
  fireEvent.click(screen.getByRole("tab", { name: "History" }));

  await waitFor(() => {
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });
  expect(screen.getByRole("alert")).toHaveTextContent("PROJECT_NOT_FOUND");
});

test("run detail shows artifact list with download links", async () => {
  const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
  fetchMock.mockResolvedValueOnce(jsonResponse({ project_root: "/tmp/demo" })); // createProject
  fetchMock.mockResolvedValueOnce(
    jsonResponse({
      runs: [
        {
          run_id: "run-1",
          status: "completed",
          mode: "auto",
          started_at: "2026-05-01T00:00:00+00:00",
          y: "y",
          x: ["x"],
        },
      ],
    })
  ); // fetchRuns
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
  ); // fetchRunDetail
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
  ); // fetchRunArtifacts

  render(<App />);
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
  fetchMock.mockResolvedValueOnce(jsonResponse({ project_root: "/tmp/demo" })); // createProject
  fetchMock.mockResolvedValueOnce(
    jsonResponse({
      runs: [
        {
          run_id: "run-1",
          status: "completed",
          mode: "auto",
          started_at: "2026-05-01T00:00:00+00:00",
          y: "y",
          x: ["x"],
        },
      ],
    })
  ); // fetchRuns
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
  ); // fetchRunDetail
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
  ); // fetchRunArtifacts

  render(<App />);
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
    jsonResponse({
      runs: [
        {
          run_id: "run-1",
          status: "completed",
          mode: "auto",
          started_at: "2026-05-01T00:00:00+00:00",
          y: "y",
          x: ["x"],
        },
      ],
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

  render(<App />);
  await fillProject();
  fireEvent.click(screen.getByRole("tab", { name: "History" }));
  await waitFor(() => screen.getByText("run-1"));
  fireEvent.click(screen.getByText("run-1"));

  await waitFor(() => screen.getByRole("button", { name: /view report/i }));
  fireEvent.click(screen.getByRole("button", { name: /view report/i }));

  const iframe = screen.getByTitle("Run report") as HTMLIFrameElement;
  expect(iframe.getAttribute("sandbox")).toBe("allow-same-origin");
});
