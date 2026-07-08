import { describe, it, expect } from "vitest";
import { groupVariablesByRole } from "./RunSnapshotAdapter";

describe("groupVariablesByRole", () => {
  it("buckets variable edges into ordered role groups", () => {
    const edges = [
      { source: "var:y:cleaned", target: "model:ols_1", op: "enters_as_outcome", params: {} },
      { source: "var:x1:cleaned", target: "model:ols_1", op: "enters_as_focal", params: {} },
      { source: "var:age:cleaned", target: "model:ols_1", op: "enters_as_covariates", params: {} },
    ];
    const groups = groupVariablesByRole(edges, "model:ols_1");
    expect(groups.map((g) => g.role)).toEqual(["outcome", "focal", "covariates"]);
    expect(groups[1].columns).toEqual(["x1"]);
  });

  it("renders empty focal as a single unspecified group", () => {
    const edges = [
      { source: "var:y:cleaned", target: "model:ols_1", op: "enters_as_outcome", params: {} },
      { source: "var:a:cleaned", target: "model:ols_1", op: "enters_as_explanatory_unspecified", params: {} },
    ];
    const groups = groupVariablesByRole(edges, "model:ols_1");
    expect(groups.some((g) => g.role === "explanatory_unspecified")).toBe(true);
  });

  it("strips forest node-hash prefixes so drawer roles show variable names, not hashes", () => {
    // v1.6.8 regression: in the cross-run forest, edge endpoints are keyed
    // "<node_hash>::<op_node_id>". columnOf must still recover "x1".
    const hash = "a".repeat(64);
    const edges = [
      { source: `${hash}::var:y:cleaned`, target: `${hash}::model:ols_1`, op: "enters_as_outcome", params: {} },
      { source: `${hash}::var:x1:cleaned`, target: `${hash}::model:ols_1`, op: "enters_as_explanatory_unspecified", params: {} },
    ];
    const groups = groupVariablesByRole(edges, `${hash}::model:ols_1`);
    expect(groups.map((g) => g.columns)).toEqual([["y"], ["x1"]]);
  });
});
