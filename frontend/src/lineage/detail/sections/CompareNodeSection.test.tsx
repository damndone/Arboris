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

// Field names copied from a real ComparePacket.to_dict() served by
// GET /compare-nodes, not invented. The first version of this test made up
// `findings` and `trust_conclusion`; the component matched the fiction and
// rendered a blocked comparison as though it were clean.
const PAYLOAD = {
  compare_id: "c1",
  relation: "ancestor_descendant",
  left: { run_id: "run-a", node_id: "model:arma_garch_1" },
  right: { run_id: "run-b", node_id: "model:arma_garch_1" },
  packet: {
    schema_version: "compare_packet_v1",
    compare_status: "blocked_by_integrity",
    reason_code: "SAMPLE_MISMATCH",
    integrity_findings: ["SAMPLE_MISMATCH", "SPLIT_HASH_MISMATCH"],
    user_safe_message:
      "The time-series runs cannot be compared until lineage and terminal artifacts are complete.",
    conclusion_diff: {
      classification: null,
      more_trustworthy: null,
      reason: "Lineage or required terminal artifacts are incomplete.",
    },
  },
};

const COMPLETE_PACKET = {
  ...PAYLOAD,
  packet: {
    schema_version: "compare_packet_v1",
    compare_status: "complete",
    integrity_findings: [],
    conclusion_diff: {
      classification: "COMPARABLE_WITH_NO_AUTOMATIC_WINNER",
      reason: "Metric changes alone do not establish that one is more trustworthy.",
    },
  },
};

const PRESENTATION_PACKET = {
  ...COMPLETE_PACKET,
  packet: {
    ...COMPLETE_PACKET.packet,
    presentation: {
      sample_identity: {
        data_changed: false,
        split_contract_changed: true,
        message: "Same sample membership; the split contract changed.",
      },
      specification_changes: ["ARMA: (1, 1) → (2, 1)"],
      forecast_metrics: [{ name: "RMSE", before: 7.44, after: 7.53 }],
      acceptance: { before: "accepted_with_warnings", after: "accepted_with_warnings" },
      conclusion: "Comparable with no automatic winner.",
    },
  },
};

const PREDICTION_TYPED_PACKET = {
  ...PAYLOAD,
  packet: {
    schema_id: "workbench.prediction.compare.v1",
    compare_status: "complete",
    comparability: "typed_same_split_plan",
    split_plan_hash: "sha256:split",
    metric_diff: { r2: { left: 0.4, right: 0.5, difference: 0.1 } },
    left: { model_id: "prediction_ridge_1" },
    right: { model_id: "prediction_lasso_1" },
  },
};

const PREDICTION_LEGACY_PACKET = {
  ...PAYLOAD,
  packet: {
    schema_id: "workbench.prediction.compare.v1",
    compare_status: "legacy_only",
    comparability: "legacy_only",
    message: "Legacy evaluation — split protocol was not persisted. The result remains readable but is not comparable with v1.8.6 predictive-research results.",
    left: { status: "legacy", model_id: "prediction_ridge_1" },
    right: { status: "legacy", model_id: "prediction_ridge_1" },
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
  it("renders typed predictive-research comparability from the durable packet", () => {
    renderSection(PREDICTION_TYPED_PACKET);

    expect(screen.getByTestId("prediction-compare-evidence")).toHaveTextContent("Prediction research comparison");
    expect(screen.getByTestId("prediction-compare-evidence")).toHaveTextContent("typed_same_split_plan");
    expect(screen.getByTestId("prediction-compare-evidence")).toHaveTextContent("sha256:split");
    expect(screen.getByTestId("prediction-compare-evidence")).toHaveTextContent("0.1");
  });

  it("renders legacy predictive-research comparison as readable but non-comparable", () => {
    renderSection(PREDICTION_LEGACY_PACKET);

    expect(screen.getByTestId("prediction-compare-evidence")).toHaveTextContent("legacy_only");
    expect(screen.getByTestId("prediction-compare-evidence")).toHaveTextContent(/Legacy evaluation — split protocol was not persisted/);
  });

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

  it("shows the stored integrity findings verbatim", () => {
    renderSection(PAYLOAD);

    expect(screen.getByText("SPLIT_HASH_MISMATCH")).toBeInTheDocument();
    expect(screen.getByText("SAMPLE_MISMATCH")).toBeInTheDocument();
  });

  it("says loudly when the backend blocked the comparison", () => {
    // The failure this replaced: a blocked packet rendered with no findings
    // and no status, so the node looked like a clean comparison.
    renderSection(PAYLOAD);

    const blocked = screen.getByTestId("compare-node-blocked");
    expect(blocked).toHaveTextContent("blocked_by_integrity");
    expect(blocked).toHaveTextContent(/cannot be compared until lineage/);
  });

  it("does not claim a blocked status on a complete comparison", () => {
    renderSection(COMPLETE_PACKET);

    expect(screen.queryByTestId("compare-node-blocked")).toBeNull();
    expect(screen.getByText("COMPARABLE_WITH_NO_AUTOMATIC_WINNER")).toBeInTheDocument();
  });

  it("carries the packet's refusal to name a winner from metrics alone", () => {
    renderSection(COMPLETE_PACKET);

    expect(screen.getByText("COMPARABLE_WITH_NO_AUTOMATIC_WINNER")).toBeInTheDocument();
    expect(screen.getByText(/do not establish that one is more trustworthy/)).toBeInTheDocument();
  });

  it("renders a compact human summary while retaining the stored packet", () => {
    renderSection(PRESENTATION_PACKET);

    expect(screen.getByText("Same sample membership; the split contract changed.")).toBeInTheDocument();
    expect(screen.getByText("ARMA: (1, 1) → (2, 1)")).toBeInTheDocument();
    expect(screen.getByText(/RMSE: 7\.44 → 7\.53/)).toBeInTheDocument();
    expect(screen.getByText(/accepted_with_warnings → accepted_with_warnings/)).toBeInTheDocument();
    expect(screen.getByText("View raw Compare JSON")).toBeInTheDocument();
  });

  it("says so when there are no findings instead of showing an empty list", () => {
    renderSection({ ...PAYLOAD, packet: { integrity_findings: [] } });

    expect(screen.getByText("No integrity findings.")).toBeInTheDocument();
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
