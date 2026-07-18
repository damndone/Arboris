import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ProjectRootProvider } from "../../../workbench/ProjectRootContext";
import { ForestContext } from "../../../workbench/ForestContext";
import type { GraphViewNode } from "../../api/graphViewTypes";
import { fetchAnalysisLoopPackets } from "../../api/analysisLoop";
import { AnalysisLoopSection } from "./AnalysisLoopSection";

vi.mock("../../api/analysisLoop", () => ({
  fetchAnalysisLoopPackets: vi.fn(),
}));

const fetchPackets = vi.mocked(fetchAnalysisLoopPackets);

function node(
  overrides: Partial<GraphViewNode> & { runs?: string[] } = {},
): GraphViewNode {
  return {
    id: "node-child",
    nodeKey: "node-child",
    raw: null,
    stage: "model",
    kind: "model",
    title: "Clustered OLS",
    summary: "OLS",
    parentStageId: null,
    trust: "ok",
    decisions: [],
    runs: ["run-child"],
    ...overrides,
  } as GraphViewNode;
}

function response(): Record<string, unknown> {
  return {
    status: "complete",
    run: {
      run_id: "run-child",
      status: "completed",
      model: "ols",
      contract_version: "ols_result_contract_v1",
      covariance: "clustered",
      covariance_wire: "clustered",
      entity_col: "company_id",
      stable_result_ids: ["coef:treatment"],
      primary_estimand: { result_id: "coef:treatment", role: "primary" },
      analysis_sample: { row_count: 428, row_order: [] },
      fingerprints: {},
    },
    source_run: {
      run_id: "run-source",
      status: "completed",
      model: "ols",
      contract_version: "ols_result_contract_v1",
      covariance: "unadjusted",
      covariance_product: "conventional",
      covariance_wire: "unadjusted",
      entity_col: null,
      stable_result_ids: ["coef:treatment"],
      primary_estimand: { result_id: "coef:treatment", role: "primary" },
      analysis_sample: { row_count: 428, row_order: [] },
      fingerprints: {},
    },
    packet: {
      child_run_id: "run-child",
      source_run_id: "run-source",
      plan_diff: {
        product_patch: { covariance: "clustered", cluster_variable: "company_id" },
        wire_patch: { covariance: "clustered", entity_col: "company_id" },
        plan_hash: "plan-hash-1",
        canonical_patch_hash: "patch-hash-1",
        invariants: { sample: "unchanged", point_estimation: "unchanged" },
      },
      validation_packet: {
        status: "complete",
        overall_status: "warning",
        checks: [
          {
            check_id: "model.standard_errors",
            status: "warning",
            severity: "warning",
            reason_code: "SMALL_CLUSTER_COUNT",
            expected: "pass",
            observed: "warning",
            evidence_refs: ["diagnostic:cluster-count"],
          },
        ],
      },
      compare_packet: {
        compare_status: "complete",
        source_run_id: "run-source",
        child_run_id: "run-child",
        target: { result_id: "coef:treatment", role: "primary" },
        data_diff: { changed: false },
        parameter_diff: { inference_config: { changed: true } },
        result_diff: { "coef:treatment": { status: "complete" } },
        conclusion_diff: {
          status: "complete",
          classification: "SIGNIFICANCE_LOST",
          target_result_id: "coef:treatment",
        },
        validation_status: "complete",
        integrity_findings: [],
      },
    },
    children: [],
  };
}

function renderSection() {
  return render(
    <ProjectRootProvider projectRoot="/tmp/project">
      <AnalysisLoopSection node={node()} />
    </ProjectRootProvider>,
  );
}

function renderSectionForActiveRun(activeRunId: string) {
  const selected = node({ runs: ["run-older", activeRunId] });
  return render(
    <ProjectRootProvider projectRoot="/tmp/project">
      <ForestContext.Provider
        value={{
          forest: {
            schemaVersion: 4,
            legacy: false,
            nodes: [selected as never],
            edges: [],
            heads: [],
            familyCount: 0,
            familyRunCount: 2,
          },
          activeRunId,
          setActiveRunId: vi.fn(),
        }}
      >
        <AnalysisLoopSection node={selected} />
      </ForestContext.Provider>
    </ProjectRootProvider>,
  );
}

describe("AnalysisLoopSection", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders backend source facts, PlanDiff, validation checks, and four-layer compare", async () => {
    fetchPackets.mockResolvedValue(response() as never);
    renderSection();

    expect(screen.getByTestId("analysis-loop-loading")).toBeInTheDocument();
    expect(await screen.findByTestId("analysis-loop-section")).toBeInTheDocument();
    expect(fetchPackets).toHaveBeenCalledWith("/tmp/project", "run-child");
    expect(screen.getByTestId("analysis-loop-run-facts")).toHaveTextContent(
      "OLS contract ols_result_contract_v1",
    );
    expect(screen.getByTestId("analysis-loop-source-facts")).toHaveTextContent(
      "conventional",
    );
    expect(screen.getByTestId("analysis-loop-plan-diff")).toHaveTextContent("company_id");
    expect(screen.getByTestId("analysis-loop-validation")).toHaveTextContent("warning");
    expect(screen.getByTestId("analysis-loop-validation")).toHaveTextContent(
      "SMALL_CLUSTER_COUNT",
    );
    expect(screen.getByTestId("analysis-loop-compare")).toHaveTextContent("complete");
    expect(screen.getByTestId("analysis-loop-compare")).toHaveTextContent("SIGNIFICANCE_LOST");
    expect(screen.getByTestId("analysis-loop-compare")).toHaveTextContent("run-source");
  });

  it("keeps an absent packet visible without inventing a target or result", async () => {
    fetchPackets.mockResolvedValue({
      ...(response() as object),
      status: "absent",
      packet: null,
      children: [],
    } as never);
    renderSection();

    expect(await screen.findByTestId("analysis-loop-section")).toBeInTheDocument();
    expect(screen.getByTestId("analysis-loop-status")).toHaveTextContent("absent");
    expect(screen.getByTestId("analysis-loop-primary-target")).toHaveTextContent(
      "Not selected",
    );
    expect(screen.queryByTestId("analysis-loop-compare")).toBeNull();
  });

  it("fetches the packet for the active run when a forest node is shared", async () => {
    fetchPackets.mockResolvedValue(response() as never);
    renderSectionForActiveRun("run-child");

    expect(await screen.findByTestId("analysis-loop-section")).toBeInTheDocument();
    expect(fetchPackets).toHaveBeenCalledWith("/tmp/project", "run-child");
  });

  it("shows a stable backend error instead of silently hiding the section", async () => {
    fetchPackets.mockRejectedValue(new Error("RUN_CONTRACT_UNSUPPORTED"));
    renderSection();

    expect(await screen.findByTestId("analysis-loop-error")).toHaveTextContent(
      "RUN_CONTRACT_UNSUPPORTED",
    );
  });
});
