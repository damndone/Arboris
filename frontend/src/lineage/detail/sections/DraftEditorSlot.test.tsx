import "@testing-library/jest-dom/vitest";
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { DraftEditorSlot } from "./DraftEditorSlot";
import { DraftActionsProvider, type DraftActionsValue } from "../../drafts/DraftActionsContext";
import { emptyRegistry, draftReducer } from "../../drafts/draftRegistry";
import type { GraphViewNode } from "../../api/graphViewTypes";

const draftNode = (over: Partial<GraphViewNode> = {}): GraphViewNode =>
  ({ id: "draft:d1", nodeKey: "draft:d1", raw: {}, stage: "model", kind: "model",
     title: "draft", parentStageId: null, trust: "ok", decisions: [],
     isDraft: true, draftId: "d1", lifecycleState: "draft", ...over }) as GraphViewNode;

function providerValue(over: Partial<DraftActionsValue> = {}): DraftActionsValue {
  const registry = draftReducer(emptyRegistry(), {
    type: "put", draftId: "d1", draftHash: "h1",
    draft: {
      draft_id: "d1", schema_version: "pipeline_draft.v1", created_at: "t", updated_at: "t",
      status: "draft", created_from: { source_node_hash: "hash_a", source_op_node_id: "model#0" },
      graph: { nodes: [{ node_type: "model", node_id: "model#0", model_family: "linear",
        model_type: "ols", schema_id: "s", editable_schema: [], editable_schema_hash: "e",
        source_ref: { source_run_id: "r", source_model_node_id: "model#0", source_op_node_id: "model#0",
          source_node_hash: "hash_a", source_context_fingerprint: "c" },
        source_params: {}, params: {} }], edges: [] },
      default_execution_mode: "rerun_child",
    } as never,
  });
  return { registry, busy: false, onForkDraft: vi.fn(), onPatch: vi.fn(),
    onValidate: vi.fn(), onExecute: vi.fn(), onDiscard: vi.fn(), ...over };
}

describe("DraftEditorSlot", () => {
  it("renders the draft editor for a draft node with a registry entry", () => {
    render(
      <DraftActionsProvider value={providerValue()}>
        <DraftEditorSlot node={draftNode()} />
      </DraftActionsProvider>,
    );
    expect(screen.getByRole("button", { name: /^validate$/i })).toBeInTheDocument();
  });

  it("renders nothing without a provider", () => {
    const { container } = render(<DraftEditorSlot node={draftNode()} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing for a non-draft node", () => {
    const { container } = render(
      <DraftActionsProvider value={providerValue()}>
        <DraftEditorSlot node={draftNode({ isDraft: false, draftId: undefined })} />
      </DraftActionsProvider>,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
