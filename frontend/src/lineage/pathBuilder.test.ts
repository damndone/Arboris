import { describe, it, expect } from "vitest";
import { buildBranchPath } from "./pathBuilder";
import type {
  DecisionViewModel,
  GraphViewModel,
  GraphViewNode,
  GraphViewEdge,
} from "./api/graphViewTypes";

function makeNode(
  id: string,
  summary: string | null = null,
  decisions: DecisionViewModel[] = [],
): GraphViewNode {
  return {
    id,
    nodeKey: id,
    raw: null,
    stage: "unknown",
    parentStageId: null,
    kind: "dataset_stage",
    title: id,
    summary: summary ?? undefined,
    trust: "ok",
    decisions,
    createdAt: "2026-05-19T00:00:00Z",
  };
}

function makeEdge(
  id: string,
  src: string,
  tgt: string,
  op = "flow",
): GraphViewEdge {
  return { id, source: src, target: tgt, op };
}

function makeGraph(
  nodes: GraphViewNode[],
  edges: GraphViewEdge[],
): GraphViewModel {
  return {
    schemaVersion: 3,
    runId: "test",
    legacy: false,
    nodes,
    edges,
    stats: {
      nodeCount: nodes.length,
      edgeCount: edges.length,
      leafCount: 0,
      hasDpCount: 0,
    },
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

  it("falls back to title when summary is null", () => {
    const g = makeGraph(
      [makeNode("raw"), makeNode("cleaned")],
      [makeEdge("e1", "raw", "cleaned")],
    );
    const out = buildBranchPath(g, "cleaned");
    expect(out).toContain("raw");
    expect(out).toContain("cleaned");
  });

  it("embeds DP info at the node when decisions present", () => {
    const dp: DecisionViewModel = {
      id: "model_type_auto_select",
      question: "Model type",
      picked: "continuous",
      alternatives: [],
      why: "",
      evidence: [],
      reviewStatus: "needed",
    };
    const g = makeGraph(
      [makeNode("cleaned", "Cleaned"), makeNode("model:ols_1", "OLS", [dp])],
      [makeEdge("e1", "cleaned", "model:ols_1")],
    );
    const out = buildBranchPath(g, "model:ols_1");
    expect(out).toContain("Model type");
    // displaySelected enrichment: "continuous" → "OLS"
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
    const nodes: GraphViewNode[] = [];
    const edges: GraphViewEdge[] = [];
    for (let i = 0; i < 150; i++) nodes.push(makeNode(`n${i}`));
    for (let i = 0; i < 149; i++)
      edges.push(makeEdge(`e${i}`, `n${i}`, `n${i + 1}`));
    const g = makeGraph(nodes, edges);
    const out = buildBranchPath(g, "n149");
    expect(out).toContain("truncated: too deep");
  });

  it("does NOT mark truncated when chain depth is exactly 100", () => {
    // 101 nodes (n0..n100), target n100 → 100 ancestors. Chain terminates
    // naturally at n0 with no further parents.
    const nodes: GraphViewNode[] = [];
    const edges: GraphViewEdge[] = [];
    for (let i = 0; i < 101; i++) nodes.push(makeNode(`n${i}`));
    for (let i = 0; i < 100; i++)
      edges.push(makeEdge(`e${i}`, `n${i}`, `n${i + 1}`));
    const g = makeGraph(nodes, edges);
    const out = buildBranchPath(g, "n100");
    expect(out).not.toContain("truncated");
    expect(out).toContain("n0");
    expect(out).toContain("n100");
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
