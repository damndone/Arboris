import { describe, it, expect } from "vitest";
import { rolesByVariable, primaryRole } from "./variableRoles";
import type { GraphViewEdge } from "../api/graphViewTypes";

function e(source: string, op: string): GraphViewEdge {
  return { id: `${source}->m`, source, target: "model:ols_1", op };
}

describe("rolesByVariable", () => {
  it("maps each variable node to the roles it holds for the model", () => {
    const edges = [
      e("var:wage:cleaned", "enters_as_outcome"),
      e("var:education:cleaned", "enters_as_focal"),
      e("var:firm:cleaned", "configures_unit"),
      e("var:firm:cleaned", "configures_cluster"),
    ];
    const m = rolesByVariable(edges, "model:ols_1");
    expect(m.get("var:wage:cleaned")).toEqual(["outcome"]);
    expect(m.get("var:firm:cleaned")).toEqual(["unit", "cluster"]);
  });

  it("ignores edges to other models and non-role edges", () => {
    const edges = [
      e("var:y:cleaned", "enters_as_outcome"),
      { id: "x", source: "stage:cleaned", target: "model:ols_1", op: "ols_robust.fit" },
      { id: "z", source: "var:a:cleaned", target: "model:other", op: "enters_as_focal" },
    ];
    const m = rolesByVariable(edges, "model:ols_1");
    expect([...m.keys()]).toEqual(["var:y:cleaned"]);
  });
});

describe("primaryRole", () => {
  it("picks the first role by canonical group order", () => {
    expect(primaryRole(["cluster", "unit"])).toBe("unit");
    expect(primaryRole(["covariates", "focal"])).toBe("focal");
  });
});
