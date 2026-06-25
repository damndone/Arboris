import { describe, it, expect } from "vitest";
import { resolveOwnerRun } from "./graphViewTypes";

describe("resolveOwnerRun", () => {
  it("prefers the active head when it owns the node (shared/deduped node)", () => {
    // active head is NOT runs[0] — the regression this guards against.
    expect(resolveOwnerRun(["run_a", "run_b", "run_c"], "run_c")).toBe("run_c");
  });

  it("falls back to the first owning run when the active head doesn't own the node", () => {
    expect(resolveOwnerRun(["run_a", "run_b"], "run_x")).toBe("run_a");
  });

  it("falls back to the first owning run when there is no active head", () => {
    expect(resolveOwnerRun(["run_a", "run_b"], undefined)).toBe("run_a");
  });

  it("returns undefined when the node has no owning runs", () => {
    expect(resolveOwnerRun([], "run_a")).toBeUndefined();
    expect(resolveOwnerRun(undefined, "run_a")).toBeUndefined();
  });
});
