import "@testing-library/jest-dom/vitest";
import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { DraftEditorSection } from "./DraftEditorSection";
import type { DraftEntry } from "../../drafts/draftRegistry";

function makeEntry(over: Partial<DraftEntry> = {}): DraftEntry {
  return {
    draftId: "d1",
    draftHash: "h1",
    validation: null,
    lifecycleState: "draft",
    sourceNodeHash: "hash_a",
    sourceOpNodeId: "model#0",
    modelType: "ols",
    draft: {
      draft_id: "d1",
      schema_version: "pipeline_draft.v1",
      created_at: "t",
      updated_at: "t",
      status: "draft",
      created_from: { source_node_hash: "hash_a", source_op_node_id: "model#0" },
      graph: {
        nodes: [
          {
            node_type: "model",
            node_id: "model#0",
            model_family: "linear",
            model_type: "ols",
            schema_id: "s1",
            editable_schema: [],
            editable_schema_hash: "eh",
            source_ref: {
              source_run_id: "run_a", source_model_node_id: "model#0",
              source_op_node_id: "model#0", source_node_hash: "hash_a",
              source_context_fingerprint: "ctx",
            },
            source_params: {},
            params: {},
          },
        ],
        edges: [],
      },
      default_execution_mode: "rerun_child",
    } as never,
    ...over,
  };
}

describe("DraftEditorSection", () => {
  it("calls onValidate when Validate is clicked", () => {
    const onValidate = vi.fn();
    render(<DraftEditorSection entry={makeEntry()} onPatch={vi.fn()} onValidate={onValidate} onExecute={vi.fn()} onDiscard={vi.fn()} busy={false} />);
    fireEvent.click(screen.getByRole("button", { name: /^validate$/i }));
    expect(onValidate).toHaveBeenCalledWith("d1");
  });

  it("disables Execute until valid", () => {
    render(<DraftEditorSection entry={makeEntry()} onPatch={vi.fn()} onValidate={vi.fn()} onExecute={vi.fn()} onDiscard={vi.fn()} busy={false} />);
    expect(screen.getByRole("button", { name: /^execute$/i })).toBeDisabled();
  });

  it("enables Execute when lifecycleState is valid", () => {
    render(<DraftEditorSection entry={makeEntry({ lifecycleState: "valid" })} onPatch={vi.fn()} onValidate={vi.fn()} onExecute={vi.fn()} onDiscard={vi.fn()} busy={false} />);
    expect(screen.getByRole("button", { name: /^execute$/i })).toBeEnabled();
  });

  it("disables the Save button while busy", () => {
    render(<DraftEditorSection entry={makeEntry()} onPatch={vi.fn()} onValidate={vi.fn()} onExecute={vi.fn()} onDiscard={vi.fn()} busy={true} />);
    expect(screen.getByRole("button", { name: /save changes/i })).toBeDisabled();
  });

  it("calls onDiscard when Discard is clicked", () => {
    const onDiscard = vi.fn();
    render(<DraftEditorSection entry={makeEntry()} onPatch={vi.fn()} onValidate={vi.fn()} onExecute={vi.fn()} onDiscard={onDiscard} busy={false} />);
    fireEvent.click(screen.getByRole("button", { name: /^discard$/i }));
    expect(onDiscard).toHaveBeenCalledWith("d1");
  });
});
