import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { RunDeletionDialog } from "./RunDeletionDialog";
import type { RunDeletionPreview } from "../api";

const deletablePreview: RunDeletionPreview = {
  run_id: "run_leaf",
  deletable: true,
  blocking_descendant_run_ids: [],
  blocking_status: null,
  artifact_counts: { figure: 1, model_result: 1 },
  report_count: 1,
  agent_session_ids: ["agent_leaf"],
  agent_event_session_ids: ["agent_leaf"],
  proposal_ids: ["proposal_leaf"],
  operation_record_ids: ["operation_leaf"],
  retained_shared_record_ids: ["proposal:shared"],
  fingerprint: "a".repeat(64),
};

describe("RunDeletionDialog", () => {
  it("requires the exact Run ID before a permanent deletion can be confirmed", () => {
    const onConfirm = vi.fn();
    render(
      <RunDeletionDialog
        preview={deletablePreview}
        onClose={vi.fn()}
        onConfirm={onConfirm}
      />,
    );

    const confirm = screen.getByRole("button", { name: "Delete permanently" });
    expect(confirm).toBeDisabled();
    expect(screen.getByText("1 report")).toBeInTheDocument();
    expect(screen.getByText("1 shared record will be retained")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Type run_leaf to confirm"), {
      target: { value: "run_leaf" },
    });
    fireEvent.click(confirm);

    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("explains why a non-leaf Run cannot be deleted and omits destructive controls", () => {
    render(
      <RunDeletionDialog
        preview={{
          ...deletablePreview,
          deletable: false,
          blocking_descendant_run_ids: ["run_child"],
        }}
        onClose={vi.fn()}
        onConfirm={vi.fn()}
      />,
    );

    expect(screen.getByText("This Run has descendants: run_child.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Delete permanently" })).toBeNull();
  });
});
