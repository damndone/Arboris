import { afterEach, beforeEach, describe, expect, it, test, vi } from "vitest";
import {
  ApiError,
  connectRunEvents,
  fetchRunDetail,
  fetchRuns,
  fetchRunArtifacts,
  getRunGraph,
  runBatchWorkflow,
  runWorkflow,
  previewFile,
  reportUrl,
  artifactDownloadUrl,
  waitForRunTerminal,
  rerunFromNode,
  createPipelineDraftFromNode,
  executePipelineDraft,
  getPipelineDraft,
  patchPipelineDraftParams,
  validatePipelineDraft,
  uploadDataset,
  createGenesisDraft,
  patchDraftNode,
  fetchProjectForest,
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

  expect(fetch).toHaveBeenCalledWith("/api/runs?project_root=%2Ftmp%2Fdemo");
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
    "/api/runs/abc?project_root=%2Ftmp%2Fdemo"
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
    "/api/runs/abc/artifacts?project_root=%2Ftmp%2Fdemo"
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
    "/api/runs/abc%20123/artifacts/report_html?project_root=%2Ftmp%2Fdemo"
  );
});

test("reportUrl encodes project_root", () => {
  const url = reportUrl("/tmp/demo", "abc");
  expect(url).toBe("/api/runs/abc/report?project_root=%2Ftmp%2Fdemo");
});

test("rerunFromNode posts context-driven rerun request body", async () => {
  (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
    jsonResponse({
      run_id: "run_child",
      new_run_id: "run_child",
      new_active_head_id: "run_child",
      focus: {
        forest_node_key: "hash_child",
        op_node_id: "model:ols_1",
        node_hash: "hash_child",
      },
      rerun_from: {
        owner_run_id: "run_c",
        op_node_id: "model:ols_1",
        node_hash: "hash_shared",
        forest_node_key: "hash_shared",
      },
    }),
  );

  await rerunFromNode("/tmp/demo", "run_c", {
    request_id: "rerun_1",
    operation: "rerun",
    context_version: "node-operation-context/v1",
    context_fingerprint: "nocv1:abc",
    owner_run_id: "run_c",
    op_node_id: "model:ols_1",
    node_hash: "hash_shared",
    forest_node_key: "hash_shared",
    owner_resolution: "active_head_contains_node",
    active_head_run_id: "run_c",
    op_overrides: { covariance: "robust" },
  });

  expect(fetch).toHaveBeenCalledWith(
    "/api/runs/run_c/rerun?project_root=%2Ftmp%2Fdemo",
    expect.objectContaining({
      method: "POST",
      headers: { "Content-Type": "application/json" },
    }),
  );
  const body = JSON.parse(
    ((fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0][1] as RequestInit)
      .body as string,
  );
  expect(body).toEqual({
    request_id: "rerun_1",
    operation: "rerun",
    context_version: "node-operation-context/v1",
    context_fingerprint: "nocv1:abc",
    owner_run_id: "run_c",
    op_node_id: "model:ols_1",
    node_hash: "hash_shared",
    forest_node_key: "hash_shared",
    owner_resolution: "active_head_contains_node",
    active_head_run_id: "run_c",
    op_overrides: { covariance: "robust" },
    from_node: "model:ols_1",
    rerun_reason: "manual_override",
  });
});

test("pipeline draft client calls draft endpoints", async () => {
  const calls: Array<{ url: string; init?: RequestInit }> = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, init });
      return new Response(
        JSON.stringify({ draft: { draft_id: "draft_1" }, draft_hash: "h1" }),
        { status: 200 },
      );
    }),
  );

  await createPipelineDraftFromNode("/tmp/project", {
    source_run_id: "run_1",
    source_model_node_id: "model_1",
    source_op_node_id: "op_1",
    source_node_hash: "hash_1",
    source_context_fingerprint: "ctx_1",
  });
  await getPipelineDraft("/tmp/project", "draft_1");
  await patchPipelineDraftParams("/tmp/project", "draft_1", {
    model_node_id: "model_1",
    base_draft_hash: "h1",
    params: { covariance: "robust" },
  });
  await validatePipelineDraft("/tmp/project", "draft_1", "rerun_child");
  await executePipelineDraft("/tmp/project", "draft_1", {
    validated_draft_hash: "h1",
    execution_mode: "rerun_child",
  });

  expect(calls.map((c) => c.url).join("\n")).toContain("/pipeline-drafts/from-node");
  expect(calls.map((c) => c.url).join("\n")).toContain("/pipeline-drafts/draft_1");
  expect(calls.map((c) => c.url).join("\n")).toContain("/pipeline-drafts/draft_1/validate");
  expect(calls.map((c) => c.url).join("\n")).toContain("/pipeline-drafts/draft_1/execute");
});

test("rerunFromNode posts manual patch payload", async () => {
  (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
    jsonResponse({
      run_id: "run_child",
      new_run_id: "run_child",
      new_active_head_id: "run_child",
      focus: null,
      rerun_from: {
        owner_run_id: "run_c",
        op_node_id: "model:ols_1",
        node_hash: "hash_shared",
        forest_node_key: "hash_shared",
      },
      produced_lineage: {
        produced_owner_run_id: "run_child",
        produced_op_node_id: null,
        produced_node_hash: null,
        rerun_request_id: "rerun_1",
        rerun_from: {
          owner_run_id: "run_c",
          op_node_id: "model:ols_1",
          node_hash: "hash_shared",
          context_fingerprint: "nocv1:abc",
          patch_id: "patch_1",
          rerun_request_id: "rerun_1",
        },
        status: "pending_index",
      },
    }),
  );

  await rerunFromNode("/tmp/demo", "run_c", {
    request_id: "rerun_1",
    operation: "rerun",
    context_version: "node-operation-context/v1",
    context_fingerprint: "nocv1:abc",
    owner_run_id: "run_c",
    op_node_id: "model:ols_1",
    node_hash: "hash_shared",
    forest_node_key: "hash_shared",
    owner_resolution: "active_head_contains_node",
    active_head_run_id: "run_c",
    op_overrides: {},
    manual_patch: {
      patch_id: "patch_1",
      patch_source: "MANUAL_EDIT",
      source_context_fingerprint: "nocv1:abc",
      editable_schema_version: "run_inputs",
      target: {
        owner_run_id: "run_c",
        op_node_id: "model:ols_1",
        node_hash: "hash_shared",
      },
      changes: [
        {
          field_id: "covariance",
          old_value: "clustered",
          new_value: "robust",
        },
      ],
    },
  });

  const body = JSON.parse(
    ((fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0][1] as RequestInit)
      .body as string,
  );
  expect(body.manual_patch).toMatchObject({
    patch_id: "patch_1",
    patch_source: "MANUAL_EDIT",
  });
  expect(body.op_overrides).toEqual({});
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
    "/api/runs/batch",
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
  expect(globalThis.EventSource).toHaveBeenCalledWith(
    "/api/runs/run-1/events?project_root=%2Ftmp%2Fdemo",
  );

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

// ── waitForRunTerminal ──────────────────────────────────────────────
// Race fix for the P0 auto-navigation. Reviewer findings:
//   - POST /runs returns status="running" immediately because the
//     orchestrator backgrounds the work; without polling the FE
//     navigates and the graph fetch beats graph.json being written,
//     landing the user on a legacy=true empty graph.
//   - These tests pin the polling contract (returns on terminal,
//     respects intervalMs, caps via maxMs).

test("waitForRunTerminal returns immediately when first poll is terminal", async () => {
  const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
  fetchMock.mockResolvedValueOnce(
    jsonResponse({
      run_id: "r1",
      status: "completed",
      mode: "auto",
      started_at: "2026-05-01T00:00:00+00:00",
      y: "y",
      x: ["x"],
    }),
  );
  const start = Date.now();
  const result = await waitForRunTerminal("/tmp/p", "r1", { intervalMs: 0 });
  // No setTimeout fired — first GET already returned completed.
  expect(Date.now() - start).toBeLessThan(50);
  expect(result.status).toBe("completed");
  expect(fetchMock).toHaveBeenCalledTimes(1);
});

test("waitForRunTerminal polls until status flips to terminal", async () => {
  const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
  const base = {
    run_id: "r2",
    mode: "auto",
    started_at: "2026-05-01T00:00:00+00:00",
    y: "y",
    x: ["x"],
  };
  fetchMock.mockResolvedValueOnce(jsonResponse({ ...base, status: "running" }));
  fetchMock.mockResolvedValueOnce(jsonResponse({ ...base, status: "running" }));
  fetchMock.mockResolvedValueOnce(jsonResponse({ ...base, status: "blocked" }));

  const result = await waitForRunTerminal("/tmp/p", "r2", { intervalMs: 0 });
  expect(result.status).toBe("blocked");
  expect(fetchMock).toHaveBeenCalledTimes(3);
});

test("waitForRunTerminal throws when maxMs cap is reached", async () => {
  const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
  const base = {
    run_id: "r3",
    status: "running",
    mode: "auto",
    started_at: "2026-05-01T00:00:00+00:00",
    y: "y",
    x: ["x"],
  };
  // Keep returning running; the cap should kick in after the first
  // iteration since maxMs is 0 (deadline crossed immediately).
  fetchMock.mockResolvedValue(jsonResponse(base));

  await expect(
    waitForRunTerminal("/tmp/p", "r3", { intervalMs: 0, maxMs: 0 }),
  ).rejects.toThrow(/still running/i);
});

test("waitForRunTerminal honors AbortSignal", async () => {
  const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
  fetchMock.mockResolvedValue(
    jsonResponse({
      run_id: "r4",
      status: "running",
      mode: "auto",
      started_at: "2026-05-01T00:00:00+00:00",
      y: "y",
      x: ["x"],
    }),
  );
  const ctrl = new AbortController();
  ctrl.abort();
  await expect(
    waitForRunTerminal("/tmp/p", "r4", {
      intervalMs: 0,
      signal: ctrl.signal,
    }),
  ).rejects.toThrow(/abort/i);
});

// ── waitForRunTerminal SSE path (T1.2) ─────────────────────────────
// jsdom doesn't ship EventSource, so the 4 polling tests above rely on
// `typeof EventSource === "undefined"` to skip straight to polling.
// These tests stub a MockEventSource so the SSE branch is exercised.
//
// MockEventSource captures listeners by event name and lets the test
// fire them on demand. Mirrors the addEventListener / onerror surface
// of the real EventSource that `connectRunEvents` uses.
class MockEventSource {
  url: string;
  listeners = new Map<string, ((e: MessageEvent) => void)[]>();
  onerror: ((e: Event) => void) | null = null;
  closed = false;
  close = vi.fn(() => {
    this.closed = true;
  });
  static instances: MockEventSource[] = [];

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

  fireError() {
    this.onerror?.(new Event("error"));
  }

  static reset() {
    this.instances = [];
  }
}

test("T1.2.a — waitForRunTerminal SSE happy path resolves on terminal event", async () => {
  MockEventSource.reset();
  vi.stubGlobal("EventSource", MockEventSource);

  const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
  // Single fetch only — the terminal-detail lookup. Intermediate
  // step events must NOT trigger fetches on the SSE path.
  fetchMock.mockResolvedValueOnce(
    jsonResponse({
      run_id: "sse-1",
      status: "completed",
      mode: "auto",
      started_at: "2026-05-01T00:00:00+00:00",
      y: "y",
      x: ["x"],
    }),
  );

  const onTick = vi.fn();
  const promise = waitForRunTerminal("/tmp/p", "sse-1", { onTick });

  // Constructor runs synchronously inside the async function, so the
  // mock instance exists before we hand control back to the awaiter.
  const source = MockEventSource.instances[MockEventSource.instances.length - 1]!;
  expect(source).toBeDefined();
  expect(source.url).toContain("/runs/sse-1/events");

  source.fire("step_start", {
    event: "step_start",
    run_id: "sse-1",
    sequence: 1,
    timestamp: "2026-05-01T00:00:01+00:00",
    step: "describe",
    message: "Building summary",
    status: null,
  });

  source.fire("workflow_completed", {
    event: "workflow_completed",
    run_id: "sse-1",
    sequence: 2,
    timestamp: "2026-05-01T00:00:05+00:00",
    step: null,
    message: "Done",
    status: "completed",
  });

  const result = await promise;
  expect(result.status).toBe("completed");
  expect(fetchMock).toHaveBeenCalledTimes(1); // only the terminal-detail GET
  // onTick must have been called with the synthesized lastEvent so
  // T1.3 (Submit page) can render "└─ describe: Building summary".
  expect(onTick).toHaveBeenCalled();
  const firstCall = onTick.mock.calls[0];
  expect(firstCall[0]).toBeNull(); // detail unavailable on intermediate ticks
  expect(firstCall[1]).toMatchObject({
    event: "step_start",
    step: "describe",
    message: "Building summary",
  });
});

test("T1.2.b — waitForRunTerminal falls back to polling on SSE error", async () => {
  MockEventSource.reset();
  vi.stubGlobal("EventSource", MockEventSource);

  const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
  // First fetch (after SSE error → polling kicks in) returns terminal.
  fetchMock.mockResolvedValueOnce(
    jsonResponse({
      run_id: "sse-2",
      status: "blocked",
      mode: "auto",
      started_at: "2026-05-01T00:00:00+00:00",
      y: "y",
      x: ["x"],
    }),
  );

  const promise = waitForRunTerminal("/tmp/p", "sse-2", { intervalMs: 0 });
  const source = MockEventSource.instances[MockEventSource.instances.length - 1]!;
  source.fireError();

  const result = await promise;
  expect(result.status).toBe("blocked");
  // Polling fallback fetched exactly once before reaching terminal.
  expect(fetchMock).toHaveBeenCalledTimes(1);
  // EventSource was closed by the fallback path so the stream doesn't leak.
  expect(source.close).toHaveBeenCalled();
});

test("T1.2.c — waitForRunTerminal abort closes EventSource and rejects", async () => {
  MockEventSource.reset();
  vi.stubGlobal("EventSource", MockEventSource);

  const ctrl = new AbortController();
  const promise = waitForRunTerminal("/tmp/p", "sse-3", { signal: ctrl.signal });
  const source = MockEventSource.instances[MockEventSource.instances.length - 1]!;
  expect(source.closed).toBe(false);

  ctrl.abort();

  await expect(promise).rejects.toThrow(/abort/i);
  expect(source.close).toHaveBeenCalled();
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
    "/api/runs/r1/graph?project_root=%2Fproj",
  );
});

test("getRunGraph throws ApiError on 404", async () => {
  (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(
    jsonResponse({ detail: "Run not found" }, 404),
  );
  await expect(getRunGraph("/proj", "missing")).rejects.toBeInstanceOf(ApiError);
});

// ── v1.6.8 — genesis clients (uploads / genesis draft / node patch / project forest) ──

describe("genesis api clients", () => {
  test("uploadDataset posts FormData with project_root and file, returns sha", async () => {
    let sentUrl = "";
    let sent: FormData | null = null;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init: RequestInit) => {
        sentUrl = url;
        sent = init.body as FormData;
        return jsonResponse({ sha256: "a".repeat(64), filename: "d.csv" });
      }),
    );
    const file = new File(["y,x\n1,2"], "d.csv", { type: "text/csv" });
    const result = await uploadDataset("/tmp/项目", file);
    expect(sentUrl).toBe("/api/uploads");
    expect(sent!.get("project_root")).toBe("/tmp/项目");
    expect(sent!.get("file")).toBe(file);
    expect(result).toEqual({ sha256: "a".repeat(64), filename: "d.csv" });
  });

  test("createGenesisDraft posts genesis payload with project_root query", async () => {
    let sentUrl = "";
    let sentBody: unknown = null;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init: RequestInit) => {
        sentUrl = url;
        sentBody = JSON.parse(init.body as string);
        return jsonResponse({ draft: { draft_id: "draft_g1" }, draft_hash: "h1" });
      }),
    );
    const result = await createGenesisDraft("/tmp/demo", {
      upload_sha256: "b".repeat(64),
      filename: "d.csv",
      sheet_names: [],
      columns: ["y", "x"],
    });
    expect(sentUrl).toBe("/api/pipeline-drafts/genesis?project_root=%2Ftmp%2Fdemo");
    expect(sentBody).toEqual({
      upload_sha256: "b".repeat(64),
      filename: "d.csv",
      sheet_names: [],
      columns: ["y", "x"],
    });
    expect(result.draft_hash).toBe("h1");
    expect(result.draft.draft_id).toBe("draft_g1");
  });

  test("patchDraftNode PATCHes node params (+optional columns)", async () => {
    let sentUrl = "";
    let sentMethod: string | undefined;
    let sentBody: unknown = null;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init: RequestInit) => {
        sentUrl = url;
        sentMethod = init.method;
        sentBody = JSON.parse(init.body as string);
        return jsonResponse({ draft: { draft_id: "draft_g1" }, draft_hash: "h2" });
      }),
    );
    const result = await patchDraftNode("/tmp/demo", "draft_g1", "table_1", {
      params: { sheet_name: "Sheet2" },
      columns: ["y", "x"],
    });
    expect(sentUrl).toBe(
      "/api/pipeline-drafts/draft_g1/nodes/table_1?project_root=%2Ftmp%2Fdemo",
    );
    expect(sentMethod).toBe("PATCH");
    expect(sentBody).toEqual({ params: { sheet_name: "Sheet2" }, columns: ["y", "x"] });
    expect(result.draft_hash).toBe("h2");
  });

  test("fetchProjectForest GETs /graph with project_root query", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      jsonResponse({
        schema_version: 2,
        nodes: {},
        edges: [],
        heads: [],
        families: [],
      }),
    );
    const result = await fetchProjectForest("/tmp/demo");
    expect(fetch).toHaveBeenCalledWith("/api/graph?project_root=%2Ftmp%2Fdemo");
    expect(result.schema_version).toBe(2);
  });

  test("genesis clients surface non-OK responses as ApiError", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(
      jsonResponse(
        { error: { code: "PROJECT_NOT_FOUND", message: "Project not found" } },
        404,
      ),
    );
    await expect(fetchProjectForest("/nope")).rejects.toMatchObject({
      name: "ApiError",
      status: 404,
      code: "PROJECT_NOT_FOUND",
      message: "Project not found",
    });
  });
});

describe("runWorkflow panel+prediction params", () => {
  it("appends entity/time/covariance/prediction params to FormData", async () => {
    let sent: FormData | null = null;
    const fetchMock = vi.fn(async (_url: string, init: RequestInit) => {
      sent = init.body as FormData;
      return new Response(JSON.stringify({ run_id: "r1", status: "running" }),
        { status: 200, headers: { "content-type": "application/json" } });
    });
    vi.stubGlobal("fetch", fetchMock);
    const file = new File(["y,x\n1,2"], "d.csv", { type: "text/csv" });
    await runWorkflow("/proj", "auto", "y", "x", file, "panel_ols", undefined, false, undefined, {
      entityCol: "firm", timeCol: "yr", covariance: "robust",
      predictionModelType: "prediction_ridge", predictionCvFolds: 3,
      predictionSamplingMethod: "smote",
      modelOptions: { random_slope: false, fit_method: "reml" },
    });
    expect(sent!.get("entity_col")).toBe("firm");
    expect(sent!.get("time_col")).toBe("yr");
    expect(sent!.get("covariance")).toBe("robust");
    expect(sent!.get("prediction_model_type")).toBe("prediction_ridge");
    expect(sent!.get("prediction_cv_folds")).toBe("3");
    expect(sent!.get("prediction_sampling_method")).toBe("smote");
    expect(sent!.get("model_options")).toBe(
      '{"random_slope":false,"fit_method":"reml"}',
    );
    vi.unstubAllGlobals();
  });

  it("fails closed instead of silently dropping non-JSON model options", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const file = new File(["y,x\n1,2"], "d.csv", { type: "text/csv" });

    await expect(
      runWorkflow("/proj", "auto", "y", "x", file, "ols", undefined, false, undefined, {
        modelOptions: { random_slope: undefined },
      }),
    ).rejects.toThrow("modelOptions");

    expect(fetchMock).not.toHaveBeenCalled();
  });
});
