import { afterEach, beforeEach, expect, test, vi } from "vitest";
import {
  ApiError,
  connectRunEvents,
  fetchRunDetail,
  fetchRuns,
  fetchRunArtifacts,
  reportUrl,
  artifactDownloadUrl,
} from "./api";

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
