import { describe, expect, it } from "vitest";
import { mergeDraftsIntoModel } from "./mergeDraftsIntoModel";
import { emptyRegistry, draftReducer } from "./draftRegistry";
import type { GraphViewModel } from "../api/graphViewTypes";
import type { PipelineDraftV1 } from "../../api";

const forestNode = (over: Partial<Record<string, unknown>> = {}) =>
  ({
    id: "node_a",
    nodeKey: "node_a",
    raw: {},
    stage: "model",
    kind: "model",
    title: "OLS",
    parentStageId: null,
    trust: "ok",
    decisions: [],
    opNodeId: "model#0",
    nodeHash: "hash_a",
    producingStage: null,
    casRef: null,
    runs: ["run_a"],
    ...over,
  }) as never;

const baseModel = (): GraphViewModel => ({
  schemaVersion: 1,
  runId: "run_a",
  legacy: false,
  nodes: [forestNode()],
  edges: [],
  stats: { nodeCount: 1, edgeCount: 0, leafCount: 1, hasDpCount: 0 },
});

const draft = (id: string, hash = "hash_a"): PipelineDraftV1 => ({
  draft_id: id,
  schema_version: "pipeline_draft.v1",
  created_at: "t",
  updated_at: "t",
  status: "draft",
  created_from: { source_node_hash: hash, source_op_node_id: "model#0" },
  graph: { nodes: [{ node_type: "model", node_id: "model#0", model_type: "ols", editable_schema: [] } as never], edges: [] },
  default_execution_mode: "rerun_child",
});

describe("mergeDraftsIntoModel", () => {
  it("injects a draft node + edge anchored by node_hash", () => {
    const reg = draftReducer(emptyRegistry(), { type: "put", draftId: "d1", draft: draft("d1"), draftHash: "h1" });
    const merged = mergeDraftsIntoModel(baseModel(), reg);
    const dn = merged.nodes.find((n) => n.draftId === "d1");
    expect(dn).toBeTruthy();
    expect(dn!.isDraft).toBe(true);
    expect(dn!.nodeKey).toBe("draft:d1");
    expect(dn!.lifecycleState).toBe("draft");
    expect(merged.edges.some((e) => e.source === "node_a" && e.target === "draft:d1")).toBe(true);
  });

  it("fans out multiple drafts from the same source", () => {
    let reg = draftReducer(emptyRegistry(), { type: "put", draftId: "d1", draft: draft("d1"), draftHash: "h1" });
    reg = draftReducer(reg, { type: "put", draftId: "d2", draft: draft("d2"), draftHash: "h2" });
    const merged = mergeDraftsIntoModel(baseModel(), reg);
    expect(merged.nodes.filter((n) => n.isDraft)).toHaveLength(2);
    expect(merged.edges.filter((e) => e.source === "node_a")).toHaveLength(2);
  });

  it("skips a draft whose source is not in the forest (degrade)", () => {
    const reg = draftReducer(emptyRegistry(), { type: "put", draftId: "d1", draft: draft("d1", "hash_missing"), draftHash: "h1" });
    const merged = mergeDraftsIntoModel(baseModel(), reg);
    expect(merged.nodes.some((n) => n.isDraft)).toBe(false);
  });

  it("is a no-op for an empty registry (same node count)", () => {
    const merged = mergeDraftsIntoModel(baseModel(), emptyRegistry());
    expect(merged.nodes).toHaveLength(1);
  });
});
