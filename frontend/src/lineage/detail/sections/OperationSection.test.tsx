import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { OperationSection } from "./OperationSection";
import { RerunContext } from "../RerunContext";
import type { RerunContextValue } from "../RerunContext";
import type { GraphViewNode, HeadSetNode } from "../../api/graphViewTypes";
import type {
  NodeOperationContextV1,
  ResolveNodeOperationContextResult,
} from "../../api/nodeOperationContext";

const { resolvedContextMock } = vi.hoisted(() => ({
  resolvedContextMock: {
    current: null as ResolveNodeOperationContextResult | null,
  },
}));

vi.mock("../NodeOperationContextProvider", () => ({
  useResolvedNodeOperationContext: () => resolvedContextMock.current,
}));

function modelNode(): HeadSetNode {
  return {
    id: "M1",
    nodeKey: "M1",
    opNodeId: "model:ols_1",
    raw: {},
    stage: "model",
    kind: "model",
    title: "OLS",
    parentStageId: null,
    trust: "ok",
    decisions: [],
    nodeHash: "M1",
    producingStage: "estimation",
    casRef: null,
    runs: ["run_a"],
    editable: true,
    opType: "ols",
    schemaId: "ols@v1",
    editableSchemaSource: "run_inputs",
    editableSchema: [
      {
        kind: "select",
        key: "covariance",
        label: "Covariance",
        options: ["robust", "clustered", "unadjusted"],
        value: "clustered", // backfilled current value (not the capabilities default)
      },
    ],
  };
}

function makeContext(overrides: Partial<NodeOperationContextV1> = {}): NodeOperationContextV1 {
  return {
    context_version: "node-operation-context/v1",
    context_kind: "executed_lineage_node",
    context_fingerprint: "nocv1:test",
    selection: {
      forest_node_key: "M1",
      node_hash: "M1",
      display_label: "OLS",
      kind: "model",
      stage: "model",
    },
    ownership: {
      active_head_run_id: "run_a",
      candidate_run_refs: [
        {
          run_id: "run_a",
          op_node_id: "model:ols_1",
          node_hash: "M1",
          is_active_head: true,
          path_contains_node: true,
        },
      ],
      candidate_run_ids: ["run_a"],
      shared_by_run_ids: ["run_a"],
      owner_run_id: "run_a",
      owner_resolution: "active_head_contains_node",
    },
    operation_target: {
      owner_run_id: "run_a",
      op_node_id: "model:ols_1",
      node_hash: "M1",
      node_state: "materialized",
      editable_schema_source: "run_inputs",
    },
    lineage_context: {
      path_run_id: "run_a",
      upstream_path: [],
      active_head_path_contains_node: true,
    },
    node_payload: {
      decisions: [],
      artifacts: [],
      editable_schema: [],
      params: {},
    },
    capabilities: {
      can_rerun: true,
      can_ask_ai: true,
      can_compare: false,
      can_rollback_focus: false,
      can_edit_params: true,
      disabled_reasons: [],
    },
    comparison_readiness: {
      can_compare: false,
      candidate_run_ids: ["run_a"],
      active_head_run_id: "run_a",
      owner_run_id: "run_a",
      shared_by_run_ids: ["run_a"],
    },
    context_diagnostics: { warnings: [], resolution_notes: [] },
    ...overrides,
  };
}

function renderWithRerun(node: GraphViewNode, submitRerun = vi.fn().mockResolvedValue(undefined)) {
  resolvedContextMock.current = { ok: true, context: makeContext() };
  const value: RerunContextValue = { submitRerun, activeRunId: "run_a" };
  render(
    <RerunContext.Provider value={value}>
      <OperationSection node={node} />
    </RerunContext.Provider>,
  );
  return { submitRerun };
}

describe("OperationSection (editable)", () => {
  it("seeds controls from the backfilled editable_schema value", () => {
    renderWithRerun(modelNode());
    const select = screen.getByRole("combobox") as HTMLSelectElement;
    expect(select.value).toBe("clustered"); // not the capabilities default "robust"
  });

  it("submit is disabled until a value changes", () => {
    renderWithRerun(modelNode());
    expect((screen.getByTestId("operation-rerun-submit") as HTMLButtonElement).disabled).toBe(true);
  });

  it("previews a manual patch before submitting rerun", async () => {
    const { submitRerun } = renderWithRerun(modelNode());
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "robust" } });
    fireEvent.click(screen.getByTestId("operation-rerun-submit"));
    expect(screen.getByTestId("manual-patch-preview")).toHaveTextContent("covariance");
    expect(submitRerun).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId("operation-rerun-submit"));
    await waitFor(() => expect(submitRerun).toHaveBeenCalledTimes(1));
    expect(submitRerun).toHaveBeenCalledWith({
      context: makeContext(),
      opOverrides: {},
      manualPatch: expect.objectContaining({
        patch_source: "MANUAL_EDIT",
        changes: [
          {
            field_id: "covariance",
            old_value: "clustered",
            new_value: "robust",
          },
        ],
      }),
    });
    await screen.findByTestId("operation-rerun-done");
  });

  it("resets edited values and submit state when context identity changes", async () => {
    const firstContext = makeContext();
    const secondContext = makeContext({
      context_fingerprint: "nocv1:next",
      selection: {
        ...firstContext.selection,
        forest_node_key: "M2",
        node_hash: "M2",
      },
      operation_target: {
        ...firstContext.operation_target,
        node_hash: "M2",
      },
    });
    const firstNode = modelNode();
    const secondNode = modelNode();
    secondNode.id = "M2";
    secondNode.nodeKey = "M2";
    secondNode.nodeHash = "M2";
    secondNode.editableSchema = [
      {
        kind: "select",
        key: "covariance",
        label: "Covariance",
        options: ["robust", "clustered", "unadjusted"],
        value: "unadjusted",
      },
    ];

    const submitRerun = vi.fn().mockResolvedValue({
      run_id: "run_child",
      new_run_id: "run_child",
      new_active_head_id: "run_child",
      focus: {
        forest_node_key: "M2",
        op_node_id: "model:ols_1",
        node_hash: "M2",
      },
      rerun_from: {
        owner_run_id: "run_a",
        op_node_id: "model:ols_1",
        node_hash: "M1",
        forest_node_key: "M1",
      },
    });
    const value: RerunContextValue = { submitRerun, activeRunId: "run_a" };
    resolvedContextMock.current = { ok: true, context: firstContext };
    const { rerender } = render(
      <RerunContext.Provider value={value}>
        <OperationSection node={firstNode} />
      </RerunContext.Provider>,
    );

    fireEvent.change(screen.getByRole("combobox"), { target: { value: "robust" } });
    fireEvent.click(screen.getByTestId("operation-rerun-submit"));
    fireEvent.click(screen.getByTestId("operation-rerun-submit"));
    await screen.findByTestId("operation-rerun-done");

    resolvedContextMock.current = { ok: true, context: secondContext };
    rerender(
      <RerunContext.Provider value={value}>
        <OperationSection node={secondNode} />
      </RerunContext.Provider>,
    );

    expect((screen.getByRole("combobox") as HTMLSelectElement).value).toBe(
      "unadjusted",
    );
    expect(screen.queryByTestId("operation-rerun-done")).toBeNull();
    expect(screen.queryByTestId("operation-rerun-error")).toBeNull();
    expect((screen.getByTestId("operation-rerun-submit") as HTMLButtonElement).disabled).toBe(true);
  });

  it("renders read-only controls and resolver failure state when context resolution fails", () => {
    resolvedContextMock.current = {
      ok: false,
      reason: "ambiguous_owner_run",
      selected_node_key: "M1",
      active_head_run_id: "run_x",
      candidate_run_refs: [
        {
          run_id: "run_a",
          op_node_id: "model:ols_1",
          node_hash: "M1",
          is_active_head: false,
          path_contains_node: true,
        },
      ],
    };
    const value: RerunContextValue = {
      submitRerun: vi.fn().mockResolvedValue(undefined),
      activeRunId: "run_x",
    };
    render(
      <RerunContext.Provider value={value}>
        <OperationSection node={modelNode()} />
      </RerunContext.Provider>,
    );

    expect(screen.queryByTestId("operation-rerun-submit")).toBeNull();
    expect(screen.getByTestId("operation-control-covariance").textContent).toContain("clustered");
    expect(screen.getByTestId("resolver-failure-state")).toHaveTextContent(
      "ambiguous_owner_run",
    );
  });

  it("does not submit when no successful context is available", async () => {
    resolvedContextMock.current = null;
    const submitRerun = vi.fn().mockResolvedValue(undefined);
    const value: RerunContextValue = { submitRerun, activeRunId: "run_a" };
    render(
      <RerunContext.Provider value={value}>
        <OperationSection node={modelNode()} />
      </RerunContext.Provider>,
    );

    expect(screen.queryByTestId("operation-rerun-submit")).toBeNull();
    expect(submitRerun).not.toHaveBeenCalled();
  });

  it("uses NodeOperationContext operation_target instead of candidateRuns for shared nodes", async () => {
    const context = makeContext();
    const node = modelNode();
    node.runs = ["run_a", "run_b", "run_c"];
    context.ownership.candidate_run_ids = ["run_a", "run_b", "run_c"];
    context.ownership.shared_by_run_ids = ["run_a", "run_b", "run_c"];
    resolvedContextMock.current = { ok: true, context };
    const submitRerun = vi.fn().mockResolvedValue(undefined);
    const value: RerunContextValue = { submitRerun, activeRunId: "run_a" };
    render(
      <RerunContext.Provider value={value}>
        <OperationSection node={node} />
      </RerunContext.Provider>,
    );
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "robust" } });
    fireEvent.click(screen.getByTestId("operation-rerun-submit"));
    fireEvent.click(screen.getByTestId("operation-rerun-submit"));
    await waitFor(() => expect(submitRerun).toHaveBeenCalledTimes(1));
    expect(submitRerun).toHaveBeenCalledWith({
      context,
      opOverrides: {},
      manualPatch: expect.objectContaining({
        patch_source: "MANUAL_EDIT",
        target: {
          owner_run_id: "run_a",
          op_node_id: "model:ols_1",
          node_hash: "M1",
        },
      }),
    });
  });

  it("degrades to read-only without a RerunProvider", () => {
    resolvedContextMock.current = { ok: true, context: makeContext() };
    render(<OperationSection node={modelNode()} />);
    expect(screen.queryByTestId("operation-rerun-submit")).toBeNull();
    // read-only row still shows the value
    expect(screen.getByTestId("operation-control-covariance").textContent).toContain("clustered");
  });
});
