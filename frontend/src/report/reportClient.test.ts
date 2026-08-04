import { describe, expect, it, vi } from "vitest";
import { generateReport, ReportGenerationError, saveAiReport } from "./reportClient";

describe("generateReport error boundary", () => {
  it("preserves structured contract violations in the user-visible error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: false,
      status: 502,
      json: async () => ({
        error: {
          code: "LLM_RESPONSE_CONTRACT_INVALID",
          message: "The report did not satisfy the evidence contract.",
          details: {
            retry_attempted: true,
            retry_count: 1,
            violations: [
              {
                code: "missing_figure",
                message: "missing figure marker coef_plot",
                subject: "coef_plot",
              },
            ],
            report_quality: {
              status: "needs_revision",
              missing_sections: ["Diagnostics and robustness"],
            },
          },
        },
      }),
    }));

    const rejection = generateReport({
      facts: [],
      scope: { run_id: "run-1", node_count: 1, node_keys: [] },
      fingerprints: [],
      figures: [],
      instruction: "Write a report",
    });

    await expect(rejection).rejects.toMatchObject({
      name: "ReportGenerationError",
      code: "LLM_RESPONSE_CONTRACT_INVALID",
      details: {
        retry_attempted: true,
        violations: [expect.objectContaining({ code: "missing_figure" })],
      },
    } satisfies Partial<ReportGenerationError>);

    await expect(rejection).rejects.toThrow(/missing figure marker coef_plot/);
    vi.unstubAllGlobals();
  });

  it("shows string violations returned by the API instead of hiding the cause", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: false,
      status: 502,
      json: async () => ({
        error: {
          code: "LLM_RESPONSE_CONTRACT_INVALID",
          message: "The report did not satisfy the evidence contract.",
          details: {
            retry_attempted: true,
            violations: ["missing section: Diagnostics and robustness"],
          },
        },
      }),
    }));

    await expect(generateReport({
      facts: [],
      scope: { run_id: "run-1", node_count: 1, node_keys: [] },
      fingerprints: [],
      figures: [],
      instruction: "Write a report",
    })).rejects.toThrow(/missing section: Diagnostics and robustness/);

    vi.unstubAllGlobals();
  });

  it("returns server-derived report metadata after a successful save", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        schema_version: "workbench-ai-report/v1",
        record: {
          fact_snapshot_hash: "hash-from-server",
          artifact_ids: ["ai_report_rpt_abc"],
          validation_status: "exportable",
        },
      }),
    }));

    await expect(saveAiReport({
      projectRoot: "/tmp/project",
      runId: "run-1",
      record: { id: "rpt_abc", text: "# Report" },
    })).resolves.toMatchObject({
      record: {
        fact_snapshot_hash: "hash-from-server",
        validation_status: "exportable",
      },
    });

    vi.unstubAllGlobals();
  });
});
