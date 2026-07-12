import { describe, expect, it } from "vitest";
import { makeOwnerResolutionSeedFixture } from "../lineage/api/nodeOperationContext";
import { buildFactTable } from "./factTable";

function fixtureWithValues() {
  const seed = makeOwnerResolutionSeedFixture();
  const model = seed.forest.nodes.find((n) => n.nodeKey === seed.sharedNodeKey)!;
  model.editableSchema = [
    { key: "model_type", kind: "select", label: "Model", value: "ols" },
    { key: "covariance", kind: "select", label: "Covariance", value: "HC1" },
    { key: "alpha", kind: "text", label: "Alpha", value: "" }, // empty → skipped
  ] as never;
  model.stats = { r_squared: 0.86, n_obs: 60 } as never;
  return seed;
}

describe("buildFactTable", () => {
  it("extracts params (from schema values) and scalar metrics with node provenance", () => {
    const seed = fixtureWithValues();
    const { facts, scope, fingerprints } = buildFactTable(seed.forest, "run_c");

    const byField = new Map(facts.map((f) => [f.field, f]));
    expect(byField.get("param:covariance")?.value).toBe("HC1");
    expect(byField.get("param:model_type")?.value).toBe("ols");
    expect(byField.get("param:alpha")).toBeUndefined(); // empty value skipped
    expect(byField.get("metric:r_squared")?.value).toBe(0.86);
    expect(byField.get("param:covariance")?.node_key).toBe(seed.sharedNodeKey);

    // ids unique + sequential-ish
    expect(new Set(facts.map((f) => f.id)).size).toBe(facts.length);
    // scope covers exactly the active run's path nodes
    expect(scope.run_id).toBe("run_c");
    expect(scope.node_keys).toContain(seed.sharedNodeKey);
    expect(fingerprints.length).toBeGreaterThan(0);
  });

  it("bare fixture yields only the fixture's own schema facts, scoped to the run", () => {
    const seed = makeOwnerResolutionSeedFixture();
    const { facts, scope } = buildFactTable(seed.forest, "run_a");
    // the seed model node ships a `formula` param; nothing else carries values
    expect(facts.map((f) => f.field)).toEqual(["param:formula"]);
    // run_a's path excludes run_c-only nodes (the report node)
    expect(scope.node_keys).not.toContain("hash_report_c");
  });
});
