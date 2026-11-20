import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, render, screen, fireEvent, waitFor } from "@testing-library/react";
import type { NodeOperationContextV1 } from "../api/nodeOperationContext";

const { rerunFromNodeMock } = vi.hoisted(() => ({ rerunFromNodeMock: vi.fn() }));
vi.mock("../../api", async () => {
  const mod = await vi.importActual<typeof import("../../api")>("../../api");
  return { ...mod, rerunFromNode: rerunFromNodeMock };
});

import { RerunProvider, useRerun } from "./RerunContext";
import type { RerunArgs, RerunContextValue } from "./RerunContext";

function makeContext(): NodeOperationContextV1 {
  return {
    context_version: "node-operation-context/v1",
    context_kind: "executed_lineage_node",
    context_fingerprint: "nocv1:test",
    selection: {
      forest_node_key: "hash_shared_model",
      node_hash: "hash_shared_model",
      display_label: "Shared OLS",
      kind: "model",
      stage: "model",
    },
    ownership: {
      active_head_run_id: "run_c",
      candidate_run_refs: [
        {
          run_id: "run_a",
          op_node_id: "model:ols_1",
          node_hash: "hash_shared_model",
          is_active_head: false,
          path_contains_node: true,
        },
        {
          run_id: "run_c",
          op_node_id: "model:ols_1",
          node_hash: "hash_shared_model",
          is_active_head: true,
          path_contains_node: true,
        },
      ],
      candidate_run_ids: ["run_a", "run_c"],
      shared_by_run_ids: ["run_a", "run_c"],
      owner_run_id: "run_c",
      owner_resolution: "active_head_contains_node",
    },
    operation_target: {
      owner_run_id: "run_c",
      op_node_id: "model:ols_1",
      node_hash: "hash_shared_model",
      node_state: "materialized",
      editable_schema_source: "run_inputs",
    },
    lineage_context: {
      path_run_id: "run_c",
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
      can_compare: true,
      can_rollback_focus: true,
      can_edit_params: true,
      disabled_reasons: [],
    },
    comparison_readiness: {
      can_compare: true,
      candidate_run_ids: ["run_a", "run_c"],
      active_head_run_id: "run_c",
      owner_run_id: "run_c",
      shared_by_run_ids: ["run_a", "run_c"],
    },
    context_diagnostics: { warnings: [], resolution_notes: [] },
  };
}

function Trigger({ args }: { args: RerunArgs }) {
  const rerun = useRerun()!;
  return (
    <button type="button" onClick={() => void rerun.submitRerun(args)}>
      go
    </button>
  );
}

function mount(args: RerunArgs) {
  render(
    <RerunProvider projectRoot="/p" runId="run_c" onRerun={() => {}}>
      <Trigger args={args} />
    </RerunProvider>,
  );
}

describe("RerunProvider submitRerun", () => {
  it.each(["switch run", "unmount"])("ignores a late submitted child after %s without cancelling its POST", async action => {
    let finish!: (response: unknown) => void;
    rerunFromNodeMock.mockImplementation(() => new Promise(resolve => {finish = resolve;}));
    let submit!: RerunContextValue["submitRerun"];
    function Probe() {submit = useRerun()!.submitRerun; return null;}
    const onRerun = vi.fn();
    const onSubmitting = vi.fn();
    const mounted = render(<RerunProvider projectRoot="/p" runId="run_c" onRerun={onRerun} onSubmitting={onSubmitting}><Probe/></RerunProvider>);
    const pending = submit({context: makeContext(), opOverrides: {covariance: "robust"}});
    expect(rerunFromNodeMock).toHaveBeenCalledOnce();
    if (action === "unmount") mounted.unmount();
    else mounted.rerender(<RerunProvider projectRoot="/p" runId="run_b" onRerun={onRerun} onSubmitting={onSubmitting}><Probe/></RerunProvider>);
    await act(async () => {finish({run_id: "old_child"}); await pending;});
    expect(onRerun).not.toHaveBeenCalled();
    expect(rerunFromNodeMock).toHaveBeenCalledOnce();
    expect(onSubmitting.mock.calls).toEqual([[true], [false]]);
  });

  it("refuses a manual POST while the existing run owner is busy", async () => {
    let submit!: RerunContextValue["submitRerun"];
    function Probe() {submit = useRerun()!.submitRerun; return null;}
    render(<RerunProvider projectRoot="/p" runId="run_c" busy onRerun={vi.fn()}><Probe/></RerunProvider>);
    await expect(submit({context: makeContext(), opOverrides: {covariance: "robust"}})).rejects.toThrow(/another run/i);
    expect(rerunFromNodeMock).not.toHaveBeenCalled();
  });

  beforeEach(() => {
    rerunFromNodeMock.mockReset();
    rerunFromNodeMock.mockResolvedValue({
      run_id: "child_1",
      new_run_id: "child_1",
      new_active_head_id: "child_1",
      focus: null,
      rerun_from: {
        owner_run_id: "run_c",
        op_node_id: "model:ols_1",
        node_hash: "hash_shared_model",
        forest_node_key: "hash_shared_model",
      },
    });
    vi.spyOn(Date, "now").mockReturnValue(12345);
    vi.spyOn(Math, "random").mockReturnValue(0.5);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("submits owner target fields from NodeOperationContextV1 instead of candidateRuns", async () => {
    const context = makeContext();
    mount({
      context,
      opOverrides: { covariance: "robust" },
      rerunReason: "user_changed_covariance",
    });
    fireEvent.click(screen.getByText("go"));
    await waitFor(() => expect(rerunFromNodeMock).toHaveBeenCalledTimes(1));
    expect(rerunFromNodeMock).toHaveBeenCalledWith("/p", "run_c", {
      request_id: "rerun_12345_i",
      operation: "rerun",
      context_version: "node-operation-context/v1",
      context_fingerprint: "nocv1:test",
      owner_run_id: "run_c",
      op_node_id: "model:ols_1",
      node_hash: "hash_shared_model",
      forest_node_key: "hash_shared_model",
      owner_resolution: "active_head_contains_node",
      active_head_run_id: "run_c",
      op_overrides: { covariance: "robust" },
      rerun_reason: "user_changed_covariance",
    });
  });

  it("submits manual_patch and clears op_overrides", async () => {
    const context = makeContext();
    const manualPatch = {
      patch_id: "patch_1",
      patch_source: "MANUAL_EDIT" as const,
      source_context_fingerprint: "nocv1:test",
      editable_schema_version: "run_inputs",
      target: {
        owner_run_id: "run_c",
        op_node_id: "model:ols_1",
        node_hash: "hash_shared_model",
      },
      changes: [
        {
          field_id: "covariance",
          old_value: "clustered",
          new_value: "robust",
        },
      ],
    };
    mount({
      context,
      opOverrides: { covariance: "robust" },
      manualPatch,
    });

    fireEvent.click(screen.getByText("go"));

    await waitFor(() => expect(rerunFromNodeMock).toHaveBeenCalledTimes(1));
    expect(rerunFromNodeMock).toHaveBeenCalledWith(
      "/p",
      "run_c",
      expect.objectContaining({
        op_overrides: {},
        manual_patch: manualPatch,
      }),
    );
  });
});
