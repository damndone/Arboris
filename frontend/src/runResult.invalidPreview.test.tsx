import "@testing-library/jest-dom/vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { RunResultView } from "./runResult";

type FetchInit = { status?: number; ok?: boolean };

function jsonResponse(body: unknown, init: FetchInit = {}): Response {
  const status = init.status ?? 200;
  return {
    ok: init.ok ?? (status >= 200 && status < 300),
    status,
    json: () => Promise.resolve(body),
  } as unknown as Response;
}

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

test("renders error state when diagnostic_summary_preview is malformed", async () => {
  const malformedDetail = {
    run_id: "run-x",
    status: "completed",
    mode: "auto",
    started_at: "2026-05-12T00:00:00+00:00",
    y: "y",
    x: ["x"],
    lineage: [],
    artifact_counts: {},
    errors: { issues: [] },
    diagnostic_summary_preview: {
      available: true,
      preview_contract_version: "1.0",
      source_schema_version: "diagnostic_summary.v1",
      preview_status: 42,
      run_lifecycle_status: "completed",
      trust_label: "ready_to_interpret",
      primary_reasons: [],
    },
  };

  fetchMock.mockImplementation((url) => {
    const u = String(url);
    if (u.includes("/runs/run-x") && !u.includes("/artifacts")) {
      return Promise.resolve(jsonResponse(malformedDetail));
    }
    if (u.includes("/artifacts")) {
      return Promise.resolve(jsonResponse({ groups: [] }));
    }
    return Promise.resolve(jsonResponse({}));
  });

  render(
    <RunResultView
      projectRoot="/tmp/test"
      runId="run-x"
      onError={() => {}}
    />,
  );

  await waitFor(() => {
    expect(screen.getByText(/Invalid diagnostic data/i)).toBeInTheDocument();
  });

  // Legacy fallback ("Trust preview unavailable" / contract_warnings) must NOT render
  // simultaneously with the validation error — that was the V1.3.2-code-review-found bug.
  expect(screen.queryByText(/diagnostic summary could not be loaded/i)).not.toBeInTheDocument();
});
