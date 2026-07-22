import "@testing-library/jest-dom/vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { RunResultView } from "./runResult";

function jsonResponse(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    json: () => Promise.resolve(body),
  } as unknown as Response;
}

const artifactPayloads: Record<string, Record<string, unknown>> = {
  "ts.report": {
    answer: "GARCH adds useful conditional-volatility evidence.",
    estimation_semantics: { strategy: "sequential", joint_likelihood: false },
    sample: { source_n: 120, training_n: 100, validation_n: 20 },
    scale: { transform: "level", lag_unit: "trading observation" },
    acceptance: { overall_status: "accepted_with_warnings" },
    warnings: [],
  },
  "ts.analysis_contract": {
    time_column: "date",
    value_column: "value",
    time_index_semantics: "business_or_trading_observations",
    transform: "level",
  },
  "ts.data_audit": { source_unchanged: true },
  "ts.arma_candidates": { candidates: [] },
  "ts.volatility_candidates": { searches: [] },
  "ts.final_diagnostics": { normality: {}, arch_lm: {} },
  "ts.forecast_metrics": { validation_n: 20, successful_forecast_n: 20, rmse: 1.1 },
  "ts.next_forecast": { target_time: null, predictive_interval: "plugin_conditional" },
  "ts.arma_vs_garch_comparison": { comparison_validation_n: 20, arma_garch: {}, arma_only: {} },
  "ts.conditional_series": { volatility: [1, 2, 3] },
  "ts.artifact_manifest": { status: "complete", artifact_count_before_manifest: 30 },
};

const originalFetch = globalThis.fetch;

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn<typeof fetch>((url) => {
    const path = String(url);
    const artifactId = Object.keys(artifactPayloads).find((id) => path.includes(`/artifacts/${id}`));
    if (artifactId) {
      return Promise.resolve(jsonResponse({
        artifact_id: artifactId,
        metadata: { run_id: "run-ts" },
        payload: artifactPayloads[artifactId],
      }));
    }
    if (path.includes("/artifacts")) {
      return Promise.resolve(jsonResponse({
        groups: [{
          artifact_type: "time_series_json",
          items: Object.keys(artifactPayloads).map((artifact_id) => ({
            artifact_id,
            path: `artifacts/time_series/${artifact_id}.json`,
            step: "arma_garch",
          })),
        }],
      }));
    }
    if (path.includes("/runs/run-ts")) {
      return Promise.resolve(jsonResponse({
        run_id: "run-ts",
        status: "completed",
        mode: "auto",
        started_at: "2026-07-20T00:00:00Z",
        y: "value",
        x: [],
        lineage: [],
        artifact_counts: {},
        errors: { issues: [] },
      }));
    }
    return Promise.resolve(jsonResponse({}));
  }));
});

afterEach(() => {
  globalThis.fetch = originalFetch;
  vi.restoreAllMocks();
});

test("loads ts artifact envelopes into the real ARMA-GARCH result card", async () => {
  render(<RunResultView projectRoot="/tmp/test" runId="run-ts" onError={() => {}} />);

  await waitFor(() => {
    expect(screen.getByLabelText("ARMA-GARCH result")).toBeInTheDocument();
  });
  expect(screen.getByText("GARCH adds useful conditional-volatility evidence.")).toBeInTheDocument();
  expect(screen.getByText(/Sequential two-stage likelihood/)).toBeInTheDocument();
  expect(screen.getByText(/Next observation time is unknown/)).toBeInTheDocument();
});
