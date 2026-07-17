import { describe, expect, it, vi } from "vitest";
import {
  authorizeCodeExecuteRisk,
  confirmDataColumnCast,
  confirmCodeExecute,
  fetchDataColumnCastContext,
  previewDataColumnCast,
} from "./dataOperations";

describe("data column cast API", () => {
  it("resolves a typed source context without guessing an artifact id", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          source_run_id: "run-1",
          source_node_id: "stage:cleaned",
          source_artifact_id: "cleaned_dataset",
          columns: [{ name: "age", dtype: "int64" }],
        }),
        { status: 200 },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await fetchDataColumnCastContext("/tmp/project", "run-1", "stage:cleaned");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/data-operations/column-cast/context?project_root=%2Ftmp%2Fproject&source_run_id=run-1&source_node_id=stage%3Acleaned",
    );
  });

  it("keeps preview and confirm requests strictly typed", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ preview: { fingerprint: "fp-1" } }), {
          status: 200,
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ operation: { record_id: "op-1" } }), {
          status: 200,
        }),
      );
    vi.stubGlobal("fetch", fetchMock);
    const request = {
      source_run_id: "run-1",
      source_node_id: "stage:cleaned",
      source_artifact_id: "cleaned_dataset",
      column: "age",
      target_dtype: "numeric" as const,
    };

    await previewDataColumnCast("/tmp/project", request);
    await confirmDataColumnCast("/tmp/project", {
      ...request,
      preview_fingerprint: "fp-1",
    });

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/data-operations/column-cast/preview?project_root=%2Ftmp%2Fproject",
      expect.objectContaining({ method: "POST" }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/data-operations/column-cast/confirm?project_root=%2Ftmp%2Fproject",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("keeps high-risk code execution as an explicit two-request contract", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            status: "risk_authorized",
            proposal: {},
            risk_authorization: {
              authorization_id: "risk-1",
              token: "opaque-token",
              operation_id: "code.execute",
              operation_version: "v1",
              proposal_id: "proposal-1",
              revision: 1,
              fingerprint: "fp-1",
              active_head_run_id: "run-1",
              expires_at: "2026-07-16T00:05:00Z",
              status: "issued",
            },
          }),
          { status: 200 },
        ),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ operation: { record_id: "op-1" } }), {
          status: 200,
        }),
      );
    vi.stubGlobal("fetch", fetchMock);
    const request = {
      source_run_id: "run-1",
      source_node_id: "stage:cleaned",
      source_artifact_id: "cleaned_dataset",
      code: "result = df",
      language: "python" as const,
      output_format: "csv" as const,
    };

    const authorized = await authorizeCodeExecuteRisk("/tmp/project", {
      ...request,
      preview_fingerprint: "fp-1",
      acknowledge_risk: true,
    });
    await confirmCodeExecute("/tmp/project", {
      ...request,
      preview_fingerprint: "fp-1",
      risk_authorization_id: authorized.risk_authorization.authorization_id,
      risk_authorization_token: authorized.risk_authorization.token,
    });

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/data-operations/code-execute/risk-authorize?project_root=%2Ftmp%2Fproject",
      expect.objectContaining({ method: "POST" }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/data-operations/code-execute/confirm?project_root=%2Ftmp%2Fproject",
      expect.objectContaining({ method: "POST" }),
    );
  });
});
