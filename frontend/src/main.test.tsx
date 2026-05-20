import "@testing-library/jest-dom/vitest";
import { act, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

function jsonResponse(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    json: () => Promise.resolve(body),
  } as unknown as Response;
}

beforeEach(() => {
  vi.resetModules();
  vi.stubGlobal("fetch", vi.fn((url: string) => {
    if (url.includes("/artifacts")) {
      return Promise.resolve(jsonResponse({ groups: [] }));
    }
    return Promise.resolve(jsonResponse({
      run_id: "run-direct",
      status: "completed",
      mode: "auto",
      started_at: "2026-05-01T00:00:00+00:00",
      y: "y",
      x: ["x"],
      lineage: [],
      artifact_counts: {},
      errors: { issues: [] },
      model_results: [],
    }));
  }));
  localStorage.clear();
  document.body.innerHTML = '<div id="root"></div>';
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  document.body.innerHTML = "";
  window.history.pushState(null, "", "/");
});

test("browser entrypoint honors direct /runs/:runId URLs", async () => {
  window.history.pushState(
    null,
    "",
    "/runs/run-direct?project_root=/tmp/demo",
  );

  await act(async () => {
    await import("./main");
  });

  await waitFor(() => {
    expect(screen.getByRole("heading", { name: /run detail/i })).toBeInTheDocument();
  });
  expect(screen.getByText("run-direct")).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: "History" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
});
