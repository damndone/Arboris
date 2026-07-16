import { describe, expect, it, vi } from "vitest";
import {
  confirmDataColumnCast,
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
});
