import { afterEach, beforeEach, expect, test, vi } from "vitest";
import {
  ApiError,
  connectRunEvents,
  fetchRunDetail,
  fetchRuns,
  fetchRunArtifacts,
  getRunGraph,
  runBatchWorkflow,
  previewFile,
  reportUrl,
  artifactDownloadUrl,
} from "./api";
import * as XLSX from "xlsx";

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn());
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  } as unknown as Response;
}

test("fetchRuns sends project_root query and returns runs array", async () => {
  (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
    jsonResponse({
      runs: [
        {
          run_id: "abc",
          status: "completed",
          mode: "auto",
          started_at: "2026-05-01T00:00:00+00:00",
          y: "y",
          x: ["x"],
        },
      ],
    })
  );

  const result = await fetchRuns("/tmp/demo");

  expect(fetch).toHaveBeenCalledWith("/runs?project_root=%2Ftmp%2Fdemo");
  expect(result.runs).toHaveLength(1);
  expect(result.runs[0].run_id).toBe("abc");
});

test("fetchRunDetail returns artifact_counts and errors", async () => {
  (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
    jsonResponse({
      run_id: "abc",
      status: "completed",
      mode: "auto",
      started_at: "2026-05-01T00:00:00+00:00",
      y: "y",
      x: ["x"],
      lineage: [],
      artifact_counts: { report: 1, model_result: 1 },
      errors: { issues: [] },
    })
  );

  const detail = await fetchRunDetail("/tmp/demo", "abc");

  expect(fetch).toHaveBeenCalledWith(
    "/runs/abc?project_root=%2Ftmp%2Fdemo"
  );
  expect(detail.artifact_counts.report).toBe(1);
  expect(detail.errors.issues).toEqual([]);
});

test("fetchRunArtifacts returns groups array", async () => {
  (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
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

  const result = await fetchRunArtifacts("/tmp/demo", "abc");

  expect(fetch).toHaveBeenCalledWith(
    "/runs/abc/artifacts?project_root=%2Ftmp%2Fdemo"
  );
  expect(result.groups[0].artifact_type).toBe("report");
  expect(result.groups[0].items[0].artifact_id).toBe("report_html");
});

test("error envelope is parsed into ApiError with code and details", async () => {
  (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
    jsonResponse(
      {
        error: {
          code: "RUN_NOT_FOUND",
          message: "Run xyz not found",
          details: { run_id: "xyz" },
        },
      },
      404
    )
  );

  await expect(fetchRunDetail("/tmp/demo", "xyz")).rejects.toMatchObject({
    name: "ApiError",
    status: 404,
    code: "RUN_NOT_FOUND",
    message: "Run xyz not found",
  });
});

test("legacy FastAPI detail string is still parsed (POST /runs upload limit)", async () => {
  (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
    jsonResponse(
      { detail: "Uploaded file exceeds project size limit." },
      413
    )
  );

  await expect(fetchRuns("/tmp/demo")).rejects.toMatchObject({
    name: "ApiError",
    status: 413,
    message: "Uploaded file exceeds project size limit.",
  });
});

test("artifactDownloadUrl encodes project_root and ids", () => {
  const url = artifactDownloadUrl("/tmp/demo", "abc 123", "report_html");
  expect(url).toBe(
    "/runs/abc%20123/artifacts/report_html?project_root=%2Ftmp%2Fdemo"
  );
});

test("reportUrl encodes project_root", () => {
  const url = reportUrl("/tmp/demo", "abc");
  expect(url).toBe("/runs/abc/report?project_root=%2Ftmp%2Fdemo");
});

test("runBatchWorkflow posts y_list and x as form data", async () => {
  (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
    jsonResponse({
      status: "completed",
      runs: [
        {
          y: "continuous_score_y",
          run_id: "run-1",
          status: "completed",
          model_id: "ols_1",
          model_type: "ols_robust",
        },
      ],
    }),
  );
  const file = new File(["y,x\n1,2\n"], "sample.csv", { type: "text/csv" });

  const result = await runBatchWorkflow(
    "/tmp/demo",
    "auto",
    ["continuous_score_y", "binary_success_y"],
    ["x1", "x2"],
    file,
  );

  expect(fetch).toHaveBeenCalledWith(
    "/runs/batch",
    expect.objectContaining({ method: "POST", body: expect.any(FormData) }),
  );
  const body = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0][1]
    .body as FormData;
  expect(body.get("project_root")).toBe("/tmp/demo");
  expect(body.get("mode")).toBe("auto");
  expect(body.get("y_list")).toBe("continuous_score_y,binary_success_y");
  expect(body.get("x")).toBe("x1,x2");
  expect(body.get("file")).toBe(file);
  expect(result.runs[0].model_type).toBe("ols_robust");
});

test("previewFile parses CSV and suggests y/x columns", async () => {
  const file = new File(
    [
      "outcome,treatment,revenue,firm_id,date\n",
      "10,1,100,a,2026-01-01\n",
      "12,0,120,b,2026-01-02\n",
      "15,1,150,c,2026-01-03\n",
    ],
    "sample.csv",
    { type: "text/csv" },
  );

  const preview = await previewFile(file);

  expect(preview.fileName).toBe("sample.csv");
  expect(preview.rowCount).toBe(3);
  expect(preview.columnCount).toBe(5);
  expect(preview.previewRows).toHaveLength(3);
  expect(preview.suggestedY).toBe("outcome");
  expect(preview.suggestedX).toEqual(["treatment", "revenue"]);
  expect(preview.columns.find((column) => column.name === "outcome")).toMatchObject({
    dtype: "numeric",
    suggestedRole: "y",
    missingRate: 0,
    uniqueCount: 3,
  });
  expect(preview.columns.find((column) => column.name === "firm_id")).toMatchObject({
    dtype: "string",
    suggestedRole: "id",
  });
});

test("previewFile parses XLSX first sheet", async () => {
  const sheet = XLSX.utils.json_to_sheet([
    { target: 1, x1: 10, x2: 100, user_id: "u1" },
    { target: 2, x1: 20, x2: 200, user_id: "u2" },
    { target: 3, x1: 30, x2: 300, user_id: "u3" },
  ]);
  const workbook = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(workbook, sheet, "Data");
  const data = XLSX.write(workbook, { bookType: "xlsx", type: "array" });
  const file = new File([data], "sample.xlsx", {
    type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  });

  const preview = await previewFile(file);

  expect(preview.fileName).toBe("sample.xlsx");
  expect(preview.rowCount).toBe(3);
  expect(preview.columnCount).toBe(4);
  expect(preview.suggestedY).toBe("target");
  expect(preview.suggestedX).toEqual(["x1", "x2"]);
  expect(preview.columns.find((column) => column.name === "x1")).toMatchObject({
    dtype: "numeric",
    suggestedRole: "x",
    mean: 20,
  });
});

test("connectRunEvents wires step events and terminal close", () => {

  const listeners: Record<string, (e: MessageEvent) => void> = {};
  const mockSource = {
    addEventListener: vi.fn(
      (type: string, handler: (e: MessageEvent) => void) => {
        listeners[type] = handler;
      },
    ),
    close: vi.fn(),
  };

  const origEventSource = (globalThis as any).EventSource;
  (globalThis as any).EventSource = vi.fn(() => mockSource);

  const callbacks = {
    onStepStart: vi.fn(),
    onStepComplete: vi.fn(),
    onStepBlocked: vi.fn(),
    onTerminal: vi.fn(),
    onError: vi.fn(),
  };

  const cleanup = connectRunEvents("/tmp/demo", "run-1", callbacks);

  // Simulate step_start
  listeners["step_start"]?.(
    new MessageEvent("step_start", {
      data: JSON.stringify({
        event: "step_start", step: "ingestion", message: "Ingesting...",
      }),
    }),
  );
  expect(callbacks.onStepStart).toHaveBeenCalledWith("ingestion", "Ingesting...");

  // Simulate step_blocked
  listeners["step_blocked"]?.(
    new MessageEvent("step_blocked", {
      data: JSON.stringify({
        event: "step_blocked", step: "validation", message: "Blocked",
      }),
    }),
  );
  expect(callbacks.onStepBlocked).toHaveBeenCalledWith("validation", "Blocked");

  // Simulate terminal -> should close
  listeners["workflow_completed"]?.(
    new MessageEvent("workflow_completed", {
      data: JSON.stringify({
        event: "workflow_completed", status: "completed", message: "Done",
      }),
    }),
  );
  expect(callbacks.onTerminal).toHaveBeenCalledWith("completed", "Done");
  expect(mockSource.close).toHaveBeenCalled();

  // Cleanup
  cleanup();

  (globalThis as any).EventSource = origEventSource;
});

test("getRunGraph returns parsed GraphResponse on 200", async () => {
  const fake = {
    schema_version: 2,
    run_id: "r1",
    legacy: false,
    stats: { node_count: 0, edge_count: 0, leaf_count: 0, has_dp_count: 0 },
    nodes: {},
    edges: {},
    branches: {},
  };
  (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(
    jsonResponse(fake),
  );
  const result = await getRunGraph("/proj", "r1");
  expect(result.schema_version).toBe(2);
  expect(result.run_id).toBe("r1");
  expect(fetch).toHaveBeenCalledWith(
    "/runs/r1/graph?project_root=%2Fproj",
  );
});

test("getRunGraph throws ApiError on 404", async () => {
  (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(
    jsonResponse({ detail: "Run not found" }, 404),
  );
  await expect(getRunGraph("/proj", "missing")).rejects.toBeInstanceOf(ApiError);
});
