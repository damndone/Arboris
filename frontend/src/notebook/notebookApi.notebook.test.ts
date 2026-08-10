import { afterEach, describe, expect, it, vi } from "vitest";

import {
  compileNotebookContext,
  confirmAndExecuteNotebookOption,
  completeNotebookOptionExecution,
  createNotebook,
  ensureNotebookProjection,
  materializeNotebookOption,
  proposeNotebookOptions,
  recordNotebookDecision,
  updateNotebookFocus,
} from "./notebookApi";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("notebookApi", () => {
  it("creates a notebook with the project root in the query", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ notebook_id: "nb_1" }), { status: 201 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await createNotebook("/tmp/project", { title: "Analysis", created_by: "user" });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/notebooks?project_root=%2Ftmp%2Fproject",
      expect.objectContaining({ method: "POST" }),
    );
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({
      title: "Analysis",
      created_by: "user",
    });
  });

  it("uses typed lifecycle endpoints and leaves response validation to the adapter", async () => {
    const fetchMock = vi.fn().mockImplementation(
      () => new Response(JSON.stringify({ context_id: "ctx_1" }), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await compileNotebookContext("/tmp/project", "nb/1");
    await ensureNotebookProjection("/tmp/project", {
      from_run_id: "run_head",
    });
    await proposeNotebookOptions("/tmp/project", "nb/1", 3);
    await recordNotebookDecision("/tmp/project", "nb/1", "opt_1", {
      decision: "selected",
      actor: "user",
    });
    await materializeNotebookOption("/tmp/project", "nb/1", "opt_1");
    await confirmAndExecuteNotebookOption("/tmp/project", "nb/1", "opt_1", {
      option_revision: 1,
      proposal_id: "proposal_1",
      proposal_revision: 1,
    });
    await completeNotebookOptionExecution("/tmp/project", "nb/1", "opt_1", {
      run_id: "run_1",
    });

    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      "/api/notebooks/nb%2F1/context/compile?project_root=%2Ftmp%2Fproject",
      "/api/notebooks/projection?project_root=%2Ftmp%2Fproject",
      "/api/notebooks/nb%2F1/options/propose?project_root=%2Ftmp%2Fproject",
      "/api/notebooks/nb%2F1/options/opt_1/decision?project_root=%2Ftmp%2Fproject",
      "/api/notebooks/nb%2F1/options/opt_1/materialize?project_root=%2Ftmp%2Fproject",
      "/api/notebooks/nb%2F1/options/opt_1/confirm-and-execute?project_root=%2Ftmp%2Fproject",
      "/api/notebooks/nb%2F1/options/opt_1/execute?project_root=%2Ftmp%2Fproject",
    ]);
    expect(JSON.parse(fetchMock.mock.calls[2][1].body)).toEqual({ count: 3 });
  });

  it("persists an explicit Notebook interaction mode with the focus request", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ notebook_id: "nb_1" }), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await updateNotebookFocus("/tmp/project", "nb_1", {
      interaction_mode: "action",
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/notebooks/nb_1/focus?project_root=%2Ftmp%2Fproject",
      expect.objectContaining({ method: "PUT" }),
    );
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({
      interaction_mode: "action",
    });
  });
});
