import { describe, it, expect, beforeEach } from "vitest";
import {
  _resetTrustWarnings,
  adaptRunGraph,
  normalizeTrust,
  safeString,
  safeStringArray,
  UnsupportedGraphSchemaError,
} from "./graphAdapter";
import type { GraphResponse, LineageNode, LineageEdge, DecisionPoint } from "../types";

// ────────────────────────────────────────────────────────────────────
// Fixture factories
// ────────────────────────────────────────────────────────────────────

function makeDP(overrides: Partial<DecisionPoint> = {}): DecisionPoint {
  return {
    decision_id: "model_type_auto_select",
    decision_id_alias: [],
    selected: "continuous",
    candidates: ["continuous", "binary"],
    source: "data_driven_default",
    contestability: {
      is_contestable: true,
      assumption_checks_needed: [],
      warnings: [],
      review_status: "needed",
    },
    reason: {
      reason_type: "data_driven_default",
      explanation: "y has many unique values",
      chosen_params_schema: null,
      chosen_params: {},
    },
    ...overrides,
  };
}

function makeNode(
  id: string,
  overrides: Partial<LineageNode> & { stage?: string | null } = {},
): LineageNode {
  return {
    id,
    kind: "dataset_stage",
    display_label: id,
    summary: null,
    created_at: "2026-05-22T00:00:00Z",
    parent_stage_id: null,
    branch_id: "main",
    trust: "ok",
    trust_reason: null,
    archived: false,
    payload_ref: null,
    decision_points: [],
    annotations: [],
    ...overrides,
  } as LineageNode;
}

function makeEdge(id: string, src: string, tgt: string): LineageEdge {
  return {
    id,
    source_id: src,
    target_id: tgt,
    op: "flow",
    params: {},
    reversible: false,
    inverse_op: null,
  };
}

function makeV2Graph(
  nodes: LineageNode[],
  edges: LineageEdge[] = [],
): GraphResponse {
  return {
    schema_version: 2,
    run_id: "r1",
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

function makeV3Graph(
  nodes: Array<LineageNode & { stage?: string | null }>,
  edges: LineageEdge[] = [],
): GraphResponse {
  return {
    ...makeV2Graph(nodes, edges),
    schema_version: 3,
  };
}

beforeEach(() => _resetTrustWarnings());

// ────────────────────────────────────────────────────────────────────
// Tests (spec §5.2)
// ────────────────────────────────────────────────────────────────────

describe("graphAdapter", () => {
  it("v2 input → every node stage is 'unknown'", () => {
    const g = makeV2Graph([makeNode("a"), makeNode("b")]);
    const m = adaptRunGraph(g);
    expect(m.nodes).toHaveLength(2);
    expect(m.nodes.every((n) => n.stage === "unknown")).toBe(true);
  });

  it("v3 input with stage → stage passes through unchanged", () => {
    const g = makeV3Graph([
      makeNode("a", { stage: "transform" }),
      makeNode("b", { stage: "model" }),
    ]);
    const m = adaptRunGraph(g);
    expect(m.nodes.find((n) => n.id === "a")?.stage).toBe("transform");
    expect(m.nodes.find((n) => n.id === "b")?.stage).toBe("model");
  });

  it.each([
    ["ok", "ok"],
    ["warning", "review"],
    ["caution", "caution"],
    ["blocker", "caution"],
    ["nonsense", "review"], // unknown → fallback per §4.4
  ] as const)(
    "trust normalisation: %s → %s",
    (backendVal, expected) => {
      expect(normalizeTrust(backendVal)).toBe(expected);
    },
  );

  it("empty decision_points → decisions: []", () => {
    const g = makeV2Graph([makeNode("a", { decision_points: [] })]);
    const m = adaptRunGraph(g);
    expect(m.nodes[0].decisions).toEqual([]);
  });

  it("multi-DP node → decisions length and order preserved", () => {
    const dp1 = makeDP({ decision_id: "model_type_auto_select", selected: "continuous" });
    const dp2 = makeDP({ decision_id: "ols_default_robust_se", selected: "HC1" });
    const dp3 = makeDP({ decision_id: "categorical_auto_dummy", selected: "first" });
    const g = makeV2Graph([
      makeNode("a", { decision_points: [dp1, dp2, dp3] }),
    ]);
    const m = adaptRunGraph(g);
    expect(m.nodes[0].decisions.map((d) => d.id)).toEqual([
      "model_type_auto_select",
      "ols_default_robust_se",
      "categorical_auto_dummy",
    ]);
  });

  it("legacy graph → legacy: true and empty nodes/edges without throwing", () => {
    const g: GraphResponse = {
      ...makeV2Graph([]),
      legacy: true,
    };
    const m = adaptRunGraph(g);
    expect(m.legacy).toBe(true);
    expect(m.nodes).toEqual([]);
    expect(m.edges).toEqual([]);
  });

  it("safe formatters: non-string selected → '', non-array candidates → []", () => {
    const dp = makeDP({
      selected: 42 as unknown as string,
      candidates: "not-an-array" as unknown as string[],
    });
    const g = makeV2Graph([makeNode("a", { decision_points: [dp] })]);
    const m = adaptRunGraph(g);
    expect(m.nodes[0].decisions[0].picked).toBe("");
    expect(m.nodes[0].decisions[0].alternatives).toEqual([]);
  });

  it("no-fabrication rule: empty chosen_params → evidence: []", () => {
    const dp = makeDP({
      reason: {
        reason_type: "data_driven_default",
        explanation: null,
        chosen_params_schema: null,
        chosen_params: {},
      },
    });
    const g = makeV2Graph([makeNode("a", { decision_points: [dp] })]);
    const m = adaptRunGraph(g);
    expect(m.nodes[0].decisions[0].evidence).toEqual([]);
  });

  it("schemaVersion preserved", () => {
    const v2 = adaptRunGraph(makeV2Graph([makeNode("a")]));
    expect(v2.schemaVersion).toBe(2);
    const v3 = adaptRunGraph(makeV3Graph([makeNode("a", { stage: "source" })]));
    expect(v3.schemaVersion).toBe(3);
  });

  it("parentStageId mapped from backend parent_stage_id (string and null cases)", () => {
    const g = makeV2Graph([
      makeNode("root"), // parent_stage_id default is null in makeNode
      makeNode("child", { parent_stage_id: "root" }),
    ]);
    const m = adaptRunGraph(g);
    expect(m.nodes.find((n) => n.id === "root")?.parentStageId).toBeNull();
    expect(m.nodes.find((n) => n.id === "child")?.parentStageId).toBe("root");
  });

  it("parentStageId: missing parent_stage_id (undefined) coerces to null [REV-2]", () => {
    // The adapter does `raw.parent_stage_id ?? null`. Cover the undefined
    // branch explicitly (the existing test covers null and string).
    const node = makeNode("orphan");
    delete (node as { parent_stage_id?: unknown }).parent_stage_id;
    const m = adaptRunGraph(makeV2Graph([node]));
    expect(m.nodes[0].parentStageId).toBeNull();
  });

  it("createdAt mapped from backend created_at", () => {
    const g = makeV2Graph([
      makeNode("a", { created_at: "2026-05-22T12:34:56Z" }),
    ]);
    const m = adaptRunGraph(g);
    expect(m.nodes[0].createdAt).toBe("2026-05-22T12:34:56Z");
  });

  it.each([
    ["future_super_stage", "unknown"],
    ["", "unknown"],
    [null, "unknown"],
    [undefined, "unknown"],
  ] as const)(
    "v3 stage=%p → coerced to %p without throwing",
    (rawStage, expected) => {
      const node = makeNode("n", { stage: rawStage as string | null });
      const m = adaptRunGraph(makeV3Graph([node]));
      expect(m.nodes[0].stage).toBe(expected);
    },
  );

  it("v3 with missing decision_points (forward-compat) → decisions: [] without crash", () => {
    // REV-3 #4: defensive coalesce so a future backend that omits an additive
    // field doesn't melt the UI. Production v3 always sends decision_points,
    // but the adapter shouldn't crash if it's stripped by a transform layer.
    const node = makeNode("n", { stage: "model" });
    delete (node as { decision_points?: unknown }).decision_points;
    const m = adaptRunGraph(makeV3Graph([node]));
    expect(m.nodes[0].decisions).toEqual([]);
  });

  it("v3 with unknown future fields → no throw, V1.5 fields adapt, extras don't leak", () => {
    // Forward-compat: future backend versions may add fields the V1.5.0 adapter
    // has not been taught about. The adapter must (a) not crash and (b) not
    // surface those unknown fields in the GraphViewModel output.
    const dp = makeDP({ decision_id: "model_type_auto_select", selected: "ols" });
    const node = {
      ...makeNode("n1", { stage: "model", trust: "warning", decision_points: [dp] }),
      // Fabricated future-version field on the node payload:
      editable_schema: [{ key: "alpha", type: "number" }],
    } as LineageNode & { stage?: string | null };
    const graph = {
      ...makeV3Graph([node]),
      // Fabricated future-version field at the top level:
      pipeline_id: "pipe_xyz",
    } as GraphResponse & { pipeline_id?: string };

    const m = adaptRunGraph(graph);

    // (a) V1.5.0 fields adapt correctly
    expect(m.schemaVersion).toBe(3);
    expect(m.nodes).toHaveLength(1);
    const out = m.nodes[0];
    expect(out.id).toBe("n1");
    expect(out.stage).toBe("model");
    expect(out.trust).toBe("review");
    expect(out.decisions.map((d) => d.id)).toEqual(["model_type_auto_select"]);

    // (b) unknown future-version fields are NOT leaked into GraphViewModel
    expect((out as unknown as Record<string, unknown>).editable_schema).toBeUndefined();
    expect((m as unknown as Record<string, unknown>).pipeline_id).toBeUndefined();
  });

  it("unsupported schema_version throws UnsupportedGraphSchemaError", () => {
    const bad = {
      ...makeV2Graph([makeNode("a")]),
      schema_version: 99 as unknown as 1 | 2 | 3,
    };
    expect(() => adaptRunGraph(bad)).toThrow(UnsupportedGraphSchemaError);
    try {
      adaptRunGraph(bad);
    } catch (e) {
      expect((e as UnsupportedGraphSchemaError).schemaVersion).toBe(99);
    }
  });
});

// ────────────────────────────────────────────────────────────────────
// Direct helper tests
// ────────────────────────────────────────────────────────────────────

describe("safe formatters", () => {
  it("safeString returns string verbatim, fallback for non-string", () => {
    expect(safeString("hi")).toBe("hi");
    expect(safeString(42)).toBe("");
    expect(safeString(null, "x")).toBe("x");
    expect(safeString(undefined, "z")).toBe("z");
  });

  it("safeStringArray filters non-string entries", () => {
    expect(safeStringArray(["a", "b"])).toEqual(["a", "b"]);
    expect(safeStringArray(["a", 1, "b"])).toEqual(["a", "b"]);
    expect(safeStringArray("not-an-array")).toEqual([]);
    expect(safeStringArray(null)).toEqual([]);
  });
});
