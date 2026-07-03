import { describe, expect, it } from "vitest";
import {
  draftReducer,
  emptyRegistry,
  type DraftEntry,
} from "./draftRegistry";
import type { PipelineDraftV1, PipelineDraftSummary } from "../../api";

const draft = (id: string, status = "draft"): PipelineDraftV1 => ({
  draft_id: id,
  schema_version: "pipeline_draft.v1",
  created_at: "t",
  updated_at: "t",
  status,
  created_from: { source_node_hash: "hash_a", source_op_node_id: "model#0" },
  graph: { nodes: [], edges: [] },
  default_execution_mode: "rerun_child",
});

describe("draftReducer", () => {
  it("put creates a draft-state entry", () => {
    const r = draftReducer(emptyRegistry(), {
      type: "put",
      draftId: "d1",
      draft: draft("d1"),
      draftHash: "h1",
    });
    const e = r.get("d1") as DraftEntry;
    expect(e.lifecycleState).toBe("draft");
    expect(e.draftHash).toBe("h1");
  });

  it("patch resets validation and returns to draft state", () => {
    let r = draftReducer(emptyRegistry(), { type: "put", draftId: "d1", draft: draft("d1"), draftHash: "h1" });
    r = draftReducer(r, { type: "validated", draftId: "d1", validation: { status: "valid" } as never, draftHash: "h1" });
    r = draftReducer(r, { type: "patch", draftId: "d1", draft: draft("d1"), draftHash: "h2" });
    const e = r.get("d1") as DraftEntry;
    expect(e.lifecycleState).toBe("draft");
    expect(e.validation).toBeNull();
    expect(e.draftHash).toBe("h2");
  });

  it("validated -> valid/invalid by status", () => {
    let r = draftReducer(emptyRegistry(), { type: "put", draftId: "d1", draft: draft("d1"), draftHash: "h1" });
    r = draftReducer(r, { type: "validated", draftId: "d1", validation: { status: "invalid" } as never, draftHash: "h1" });
    expect((r.get("d1") as DraftEntry).lifecycleState).toBe("invalid");
  });

  it("executing -> pending, then remove drops the entry", () => {
    let r = draftReducer(emptyRegistry(), { type: "put", draftId: "d1", draft: draft("d1"), draftHash: "h1" });
    r = draftReducer(r, { type: "executing", draftId: "d1" });
    expect((r.get("d1") as DraftEntry).lifecycleState).toBe("pending");
    r = draftReducer(r, { type: "remove", draftId: "d1" });
    expect(r.has("d1")).toBe(false);
  });

  it("revertToDraft returns a stuck entry to editable draft state", () => {
    let r = draftReducer(emptyRegistry(), { type: "put", draftId: "d1", draft: draft("d1"), draftHash: "h1" });
    r = draftReducer(r, { type: "validating", draftId: "d1" });
    r = draftReducer(r, { type: "revertToDraft", draftId: "d1" });
    const e = r.get("d1") as DraftEntry;
    expect(e.lifecycleState).toBe("draft");
    expect(e.validation).toBeNull();
  });

  it("hydrate loads summaries as draft entries", () => {
    const summaries: PipelineDraftSummary[] = [
      { draft_id: "d1", status: "draft", draft_hash: "h1", source_node_hash: "hash_a", source_op_node_id: "model#0" },
    ];
    const r = draftReducer(emptyRegistry(), { type: "hydrate", summaries });
    expect((r.get("d1") as DraftEntry).lifecycleState).toBe("draft");
    expect((r.get("d1") as DraftEntry).sourceNodeHash).toBe("hash_a");
  });
});
