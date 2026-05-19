import { describe, it, expect } from "vitest";
import { buildBranchPath } from "./pathBuilder";
import type { GraphResponse, LineageNode, LineageEdge, DecisionPoint } from "./types";

function makeNode(
  id: string,
  summary: string | null = null,
  decision_points: DecisionPoint[] = [],
): LineageNode {
  return {
    id,
    kind: "dataset_stage",
    display_label: id,
    summary,
    created_at: "2026-05-19T00:00:00Z",
    parent_stage_id: null,
    branch_id: "main",
    trust: "ok",
    trust_reason: null,
    archived: false,
    payload_ref: null,
    decision_points,
    annotations: [],
  };
}

function makeEdge(id: string, src: string, tgt: string, op = "flow"): LineageEdge {
  return {
    id,
    source_id: src,
    target_id: tgt,
    op,
    params: {},
    reversible: false,
    inverse_op: null,
  };
}

function makeGraph(nodes: LineageNode[], edges: LineageEdge[]): GraphResponse {
  return {
    schema_version: 2,
    run_id: "test",
    legacy: false,
    stats: {
      node_count: nodes.length,
      edge_count: edges.length,
      leaf_count: 0,
      has_dp_count: 0,
    },
    nodes: Object.fromEntries(nodes.map((n) => [n.id, n])),
    edges: Object.fromEntries(edges.map((e) => [e.id, e])),
    branches: {},
  };
}

describe("pathBuilder", () => {
  it("builds linear root-to-target prose with summaries", () => {
    const g = makeGraph(
      [
        makeNode("raw", "Raw: 35 rows × 3 cols"),
        makeNode("cleaned", "Cleaned: 32 rows (3 dropped)"),
        makeNode("model:ols_1", "OLS (HC1, n=32)"),
      ],
      [
        makeEdge("e1", "raw", "cleaned"),
        makeEdge("e2", "cleaned", "model:ols_1", "ols.fit"),
      ],
    );
    const out = buildBranchPath(g, "model:ols_1");
    expect(out).toContain("Raw: 35 rows × 3 cols");
    expect(out).toContain("Cleaned: 32 rows (3 dropped)");
    expect(out).toContain("→");
    expect(out).toContain("OLS (HC1, n=32)");
  });

  it("falls back to display_label when summary is null", () => {
    const g = makeGraph(
      [makeNode("raw"), makeNode("cleaned")],
      [makeEdge("e1", "raw", "cleaned")],
    );
    const out = buildBranchPath(g, "cleaned");
    expect(out).toContain("raw");
    expect(out).toContain("cleaned");
  });

  it("embeds DP info at the node when decision_points present", () => {
    const dp: DecisionPoint = {
      decision_id: "model_type_auto_select",
      decision_id_alias: [],
      selected: "continuous",
      candidates: [],
      source: "data_driven_default",
      contestability: {
        is_contestable: true,
        assumption_checks_needed: [],
        warnings: [],
        review_status: "needed",
      },
      reason: {
        reason_type: "data_driven_default",
        explanation: null,
        chosen_params_schema: null,
        chosen_params: { y_unique: 32, y_dtype: "float64" },
      },
    };
    const g = makeGraph(
      [makeNode("cleaned", "Cleaned"), makeNode("model:ols_1", "OLS", [dp])],
      [makeEdge("e1", "cleaned", "model:ols_1")],
    );
    const out = buildBranchPath(g, "model:ols_1");
    expect(out).toContain("Model type");
    expect(out).toContain("OLS");
  });

  it("detects cycles and suffixes [truncated: cycle]", () => {
    const g = makeGraph(
      [makeNode("a"), makeNode("b")],
      [makeEdge("e1", "a", "b"), makeEdge("e2", "b", "a")],
    );
    const out = buildBranchPath(g, "b");
    expect(out).toContain("truncated: cycle");
  });

  it("caps at 100 hops with [truncated: too deep]", () => {
    const nodes: LineageNode[] = [];
    const edges: LineageEdge[] = [];
    for (let i = 0; i < 150; i++) nodes.push(makeNode(`n${i}`));
    for (let i = 0; i < 149; i++) edges.push(makeEdge(`e${i}`, `n${i}`, `n${i + 1}`));
    const g = makeGraph(nodes, edges);
    const out = buildBranchPath(g, "n149");
    expect(out).toContain("truncated: too deep");
  });

  it("picks lexicographically smallest source when multi-parent", () => {
    const g = makeGraph(
      [makeNode("zzz"), makeNode("aaa"), makeNode("target")],
      [makeEdge("e1", "zzz", "target"), makeEdge("e2", "aaa", "target")],
    );
    const out = buildBranchPath(g, "target");
    expect(out).toContain("aaa");
    expect(out).not.toContain("zzz");
  });

  it("returns just target name for a root node (no parents)", () => {
    const g = makeGraph([makeNode("root", "Root summary")], []);
    expect(buildBranchPath(g, "root")).toContain("Root summary");
  });
});
