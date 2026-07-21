// The drawer for a stored comparison node.
//
// The node exists so a conclusion survives a reload, so the section must read
// the stored packet rather than recomputing a diff, and must name the two runs
// it read — a comparison whose sides are invisible cannot be checked.

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../../api", async () => {
  const actual = await vi.importActual<typeof import("../../../api")>("../../../api");
  return { ...actual, deleteCompareNode: vi.fn().mockResolvedValue({ deleted: "c1" }) };
});

import { deleteCompareNode } from "../../../api";
import { ProjectRootProvider } from "../../../workbench/ProjectRootContext";
import { ForestContext } from "../../../workbench/ForestContext";
import type { GraphViewNode } from "../../api/graphViewTypes";
import { CompareNodeSection, isCompareNode } from "./CompareNodeSection";

function node(compare: unknown): GraphViewNode {
  return {
    id: "c1",
    nodeKey: "c1",
    raw: { compare },
    stage: "compare",
    kind: "compare",
    title: "Comparison",
    parentStageId: null,
    trust: "ok",
    decisions: [],
  } as unknown as GraphViewNode;
}

const PAYLOAD = {
  compare_id: "c1",
  relation: "ancestor_descendant",
  left: { run_id: "run-a", node_id: "model:arma_garch_1" },
  right: { run_id: "run-b", node_id: "model:arma_garch_1" },
  packet: {
    findings: ["SPLIT_HASH_MISMATCH"],
    trust_conclusion: {
      classification: "COMPARABLE_WITH_NO_AUTOMATIC_WINNER",
      reason: "Metric changes alone do not establish that one is more trustworthy.",
    },
  },
};

const refetch = vi.fn();

function renderSection(compare: unknown) {
  return render(
    <ProjectRootProvider projectRoot="/p">
      <ForestContext.Provider
        value={{
          forest: { nodes: [], edges: [] } as never,
          activeRunId: "run-a",
          setActiveRunId: vi.fn(),
          refetch,
        }}
      >
        <CompareNodeSection node={node(compare)} />
      </ForestContext.Provider>
    </ProjectRootProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("CompareNodeSection", () => {
  it("names both runs so the comparison can be checked", () => {
    renderSection(PAYLOAD);

    expect(screen.getByText("run-a")).toBeInTheDocument();
    expect(screen.getByText("run-b")).toBeInTheDocument();
  });

  it("states the lineage relation rather than leaving it implied", () => {
    renderSection(PAYLOAD);

    expect(screen.getByText(/the baseline produced the other run/)).toBeInTheDocument();
  });

  it("says when the two runs are unrelated", () => {
    renderSection({ ...PAYLOAD, relation: "unrelated" });

    expect(screen.getByText(/no lineage relation/)).toBeInTheDocument();
  });

  it("shows the stored comparability findings verbatim", () => {
    renderSection(PAYLOAD);

    expect(screen.getByText("SPLIT_HASH_MISMATCH")).toBeInTheDocument();
  });

  it("carries the packet's refusal to name a winner from metrics alone", () => {
    renderSection(PAYLOAD);

    expect(screen.getByText("COMPARABLE_WITH_NO_AUTOMATIC_WINNER")).toBeInTheDocument();
    expect(screen.getByText(/do not establish that one is more trustworthy/)).toBeInTheDocument();
  });

  it("says so when there are no findings instead of showing an empty list", () => {
    renderSection({ ...PAYLOAD, packet: { findings: [] } });

    expect(screen.getByText("No comparability findings.")).toBeInTheDocument();
  });

  it("removes the comparison and reloads the forest", async () => {
    renderSection(PAYLOAD);

    fireEvent.click(screen.getByRole("button", { name: /remove comparison/i }));

    await waitFor(() => expect(deleteCompareNode).toHaveBeenCalledWith("/p", "c1"));
    expect(refetch).toHaveBeenCalled();
  });

  it("renders nothing for a node that carries no comparison payload", () => {
    const { container } = renderSection(undefined);

    expect(container).toBeEmptyDOMElement();
  });

  it("identifies compare nodes by kind", () => {
    expect(isCompareNode(node(PAYLOAD))).toBe(true);
    expect(isCompareNode({ ...node(PAYLOAD), kind: "model" })).toBe(false);
  });
});
