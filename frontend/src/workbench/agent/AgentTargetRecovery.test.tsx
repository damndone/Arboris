import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { AgentTargetRecovery } from "./AgentTargetRecovery";

const content = JSON.stringify({ ok: false, error: "ANALYSIS_TARGET_CONFLICT", output: {
  status: "needs_target_decision", executed: false, recovery: {
    schema: "workbench.analysis-target-recovery.v1", status: "needs_target_decision",
    message: "The requested result conflicts with the source primary estimand. Nothing was submitted or executed.",
    source_run_id: "source-a", requested_result_id: "coef:control", primary_result_id: "coef:treatment",
    steps: ["Review the source.", "Draft correction options.", "Continue independent approved steps."],
    options: [
      { id: "preserve_requested_target", label: "Keep requested target; review compatible sources", prompt: "Keep coef:control and draft a correction plan. Do not execute a substitute." },
      { id: "review_source_primary", label: "Review a plan using the source primary", prompt: "Draft a plan for coef:treatment for review. Do not execute the changed analysis." },
    ],
  },
} });

describe("AgentTargetRecovery", () => {
  it("shows the conflict and generated plan without submitting anything", () => {
    const select = vi.fn();
    render(<AgentTargetRecovery content={content} onSelect={select} disabled={false} />);
    expect(screen.getByRole("status")).toHaveTextContent("Nothing was submitted or executed");
    expect(screen.getByText(/Requested: coef:control/)).toBeInTheDocument();
    expect(screen.getByText(/Source primary: coef:treatment/)).toBeInTheDocument();
    expect(screen.getByText("Draft correction options.")).toBeInTheDocument();
    expect(select).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Keep requested target; review compatible sources" }));
    expect(select).toHaveBeenCalledTimes(1);
    expect(select).toHaveBeenCalledWith("Keep coef:control and draft a correction plan. Do not execute a substitute.");
  });

  it("makes primary-target plan review an explicit choice, disabled during a live turn", () => {
    const select = vi.fn();
    const view = render(<AgentTargetRecovery content={content} onSelect={select} disabled />);
    const primary = screen.getByRole("button", { name: "Review a plan using the source primary" });
    fireEvent.click(primary);
    expect(select).not.toHaveBeenCalled();
    view.rerender(<AgentTargetRecovery content={content} onSelect={select} disabled={false} />);
    fireEvent.click(primary);
    expect(select).toHaveBeenCalledTimes(1);
    expect(select).toHaveBeenCalledWith("Draft a plan for coef:treatment for review. Do not execute the changed analysis.");
  });

  it("does not manufacture correction options for ordinary failures or malformed messages", () => {
    const select = vi.fn();
    const view = render(<AgentTargetRecovery content='{"ok":false,"error":"ValueError"}' onSelect={select} disabled={false} />);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    view.rerender(<AgentTargetRecovery content="not-json" onSelect={select} disabled={false} />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});
