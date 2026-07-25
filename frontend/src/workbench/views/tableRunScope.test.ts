import { describe, expect, it } from "vitest";
import { resolveTableRunScope } from "./tableRunScope";
import type { ForestViewModel, HeadSetNode } from "../../lineage/api/graphViewTypes";

function head(runId: string, rerunOf: string | null, createdAt: string) {
  return {
    runId,
    headNodeHash: null,
    fromNode: null,
    rerunOf,
    rerunReason: null,
    status: "completed",
    createdAt,
  };
}

function node(nodeKey: string, runs: string[]): HeadSetNode {
  return { nodeKey, runs } as unknown as HeadSetNode;
}

/** genesis-a  →  rerun-b  →  rerun-c      (one chain)
 *  genesis-x                              (an unrelated chain) */
function forest(): ForestViewModel {
  return {
    schemaVersion: 1,
    legacy: false,
    nodes: [
      node("node:model-c", ["rerun-c"]),
      node("node:data-a", ["genesis-a", "rerun-b", "rerun-c"]),
      node("node:model-x", ["genesis-x"]),
    ],
    edges: [],
    heads: [
      head("genesis-a", null, "2026-07-24T10:00:00Z"),
      head("rerun-b", "genesis-a", "2026-07-24T11:00:00Z"),
      head("rerun-c", "rerun-b", "2026-07-24T12:00:00Z"),
      head("genesis-x", null, "2026-07-24T13:00:00Z"),
    ],
    familyCount: 2,
    familyRunCount: 4,
  };
}

describe("resolveTableRunScope", () => {
  it("shows every run in the project when nothing is selected", () => {
    // Artifacts saved against a source run must not vanish just because the
    // active head moved to a later, unrelated run.
    expect(
      resolveTableRunScope({
        forest: forest(),
        activeRunId: "genesis-x",
        selectedKey: null,
        fallbackRunId: "genesis-x",
      }),
    ).toEqual(["genesis-x", "rerun-c", "rerun-b", "genesis-a"]);
  });

  it("shows the selected node's whole lineage chain, newest first", () => {
    expect(
      resolveTableRunScope({
        forest: forest(),
        activeRunId: "rerun-c",
        selectedKey: "node:model-c",
        fallbackRunId: "rerun-c",
      }),
    ).toEqual(["rerun-c", "rerun-b", "genesis-a"]);
  });

  it("stops at the chain root and never crosses into an unrelated chain", () => {
    expect(
      resolveTableRunScope({
        forest: forest(),
        activeRunId: "genesis-x",
        selectedKey: "node:model-x",
        fallbackRunId: "genesis-x",
      }),
    ).toEqual(["genesis-x"]);
  });

  it("prefers the active head when a deduplicated node is shared across runs", () => {
    // node:data-a is identical in three runs; the chain must be anchored on the
    // run the user is actually looking at, not on array order.
    expect(
      resolveTableRunScope({
        forest: forest(),
        activeRunId: "rerun-b",
        selectedKey: "node:data-a",
        fallbackRunId: "rerun-b",
      }),
    ).toEqual(["rerun-b", "genesis-a"]);
  });

  it("falls back to the single URL run when there is no forest", () => {
    expect(
      resolveTableRunScope({
        forest: null,
        activeRunId: null,
        selectedKey: "node:model-c",
        fallbackRunId: "legacy-run",
      }),
    ).toEqual(["legacy-run"]);
  });

  it("survives a rerunOf cycle instead of looping forever", () => {
    const cyclic = forest();
    cyclic.heads = [
      head("a", "b", "2026-07-24T10:00:00Z"),
      head("b", "a", "2026-07-24T11:00:00Z"),
    ];
    cyclic.nodes = [node("node:cycle", ["a"])];
    // The point is termination and no repeats; ordering is newest-first as usual.
    const scope = resolveTableRunScope({
      forest: cyclic,
      activeRunId: "a",
      selectedKey: "node:cycle",
      fallbackRunId: "a",
    });
    expect([...scope].sort()).toEqual(["a", "b"]);
  });
});
