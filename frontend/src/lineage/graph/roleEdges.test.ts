import { describe, it, expect } from "vitest";
import { roleEdgeStyle, isRoleOp, suppressAggregateEdges } from "./roleEdges";
import type { GraphViewEdge } from "../api/graphViewTypes";

describe("roleEdgeStyle", () => {
  it("solid for substantive/identification/exposure roles", () => {
    expect(roleEdgeStyle("enters_as_focal").strokeDasharray).toBeUndefined();
    expect(roleEdgeStyle("identifies_as_instruments").strokeDasharray).toBeUndefined();
    expect(roleEdgeStyle("offsets_as_exposure").strokeDasharray).toBeUndefined();
  });
  it("dashed for unit/time/cluster", () => {
    expect(roleEdgeStyle("configures_unit").strokeDasharray).toBe("4 4");
    expect(roleEdgeStyle("configures_cluster").strokeDasharray).toBe("4 4");
  });
  it("colours the edge by role", () => {
    expect(roleEdgeStyle("enters_as_outcome").stroke).toBe("var(--role-outcome)");
  });
});

describe("isRoleOp", () => {
  it("recognises role ops only", () => {
    expect(isRoleOp("enters_as_focal")).toBe(true);
    expect(isRoleOp("ols_robust.fit")).toBe(false);
    expect(isRoleOp(undefined)).toBe(false);
  });
});

describe("suppressAggregateEdges", () => {
  it("drops stage→model fit edge when role edges feed that model", () => {
    const edges: GraphViewEdge[] = [
      { id: "1", source: "stage:cleaned", target: "model:ols_1", op: "ols_robust.fit" },
      { id: "2", source: "var:y:cleaned", target: "model:ols_1", op: "enters_as_outcome" },
      { id: "3", source: "model:ols_1", target: "report:html", op: "render_report" },
    ];
    const out = suppressAggregateEdges(edges);
    expect(out.map((e) => e.id)).toEqual(["2", "3"]);
  });
  it("keeps the fit edge when the model has no role edges (legacy run)", () => {
    const edges: GraphViewEdge[] = [
      { id: "1", source: "stage:cleaned", target: "model:ols_1", op: "ols_robust.fit" },
    ];
    expect(suppressAggregateEdges(edges).map((e) => e.id)).toEqual(["1"]);
  });

  it("drops the fit edge in the forest projection (hash-prefixed stage id)", () => {
    const edges: GraphViewEdge[] = [
      { id: "1", source: "h1::stage:cleaned", target: "h2::model:ols_1", op: "ols_robust.fit" },
      { id: "2", source: "h1::var:y:cleaned", target: "h2::model:ols_1", op: "enters_as_outcome" },
    ];
    expect(suppressAggregateEdges(edges).map((e) => e.id)).toEqual(["2"]);
  });
});
