import { describe, expect, test, vi } from "vitest";
import { openDedicated, type DedicatedContext } from "./dedicatedOperations";

const op = (surface?: string) => ({ id: "x", execution: { kind: "dedicated", surface } }) as never;
const dataset = { kind: "dataset_node", run_id: "r", node_id: "n", artifact_id: "a" } as const;

function context(): DedicatedContext {
  return { focus: vi.fn(), setView: vi.fn(), openNewAnalysis: vi.fn(), openAnalyze: vi.fn(), closeAnalyze: vi.fn(), proposeFork: vi.fn(async () => {}) };
}

describe("opening a dedicated operation where the catalog says it lives", () => {
  test("a view surface focuses the target and opens that view", async () => {
    const ctx = context();
    expect(await openDedicated(op("data"), dataset, ctx)).toBeNull();
    expect(ctx.focus).toHaveBeenCalledWith(dataset);
    expect(ctx.setView).toHaveBeenCalledWith("data");
    expect(ctx.closeAnalyze).toHaveBeenCalled();
  });

  test("the wizard, the builder, and an unknown surface", async () => {
    const ctx = context();
    await openDedicated(op("new_analysis"), undefined, ctx);
    expect(ctx.openNewAnalysis).toHaveBeenCalled();
    await openDedicated(op("analyze"), dataset, ctx);
    expect(ctx.openAnalyze).toHaveBeenCalled();
    await openDedicated(op(undefined), dataset, ctx);
    expect(ctx.setView).toHaveBeenLastCalledWith("graph");
  });

  test("a branch needs a saved step and reports a failed proposal", async () => {
    const ctx = context();
    expect(await openDedicated(op("agent"), undefined, ctx)).toBe("Select a saved step before creating a branch.");
    ctx.proposeFork = vi.fn(async () => { throw new Error("stale head"); });
    expect(await openDedicated(op("agent"), dataset, ctx)).toBe("stale head");
    expect(ctx.closeAnalyze).not.toHaveBeenCalled();
  });
});
