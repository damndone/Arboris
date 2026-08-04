import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ReportPreviewPanel } from "./ReportPreviewPanel";

vi.mock("../workbench/agent/AgentSurfaceContext", () => ({
  useAgentSurfaceOptional: () => null,
}));

describe("ReportPreviewPanel", () => {
  it("starts docked and supports floating, pinning, and collapsing", () => {
    render(
      <ReportPreviewPanel
        value=""
        onChange={vi.fn()}
        onRevise={vi.fn()}
        busy={false}
      >
        <div data-testid="preview-draft">Draft report</div>
      </ReportPreviewPanel>,
    );

    const panel = screen.getByTestId("report-preview-panel");
    expect(panel).toHaveAttribute("data-layout", "docked");
    expect(screen.getByTestId("preview-draft")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Pin preview" }));
    expect(panel).toHaveAttribute("data-layout", "floating");
    expect(panel).toHaveAttribute("data-pinned", "true");
    const dragHandle = screen.getByRole("button", { name: "Drag report preview" });
    const originalLeft = panel.style.getPropertyValue("--report-preview-left");
    fireEvent.keyDown(dragHandle, { key: "ArrowRight" });
    expect(panel.style.getPropertyValue("--report-preview-left")).not.toBe(originalLeft);
    fireEvent.click(screen.getByRole("button", { name: "Make preview larger" }));
    expect(panel).toHaveStyle({ width: "760px" });
    fireEvent.click(screen.getByRole("button", { name: "Unpin preview" }));
    expect(panel).toHaveAttribute("data-pinned", "false");

    fireEvent.click(screen.getByRole("button", { name: "Collapse preview" }));
    expect(screen.queryByTestId("preview-draft")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Expand preview" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Expand preview" }));
    expect(screen.getByTestId("preview-draft")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Dock preview" }));
    expect(panel).toHaveAttribute("data-layout", "docked");
    fireEvent.click(screen.getByRole("button", { name: "Float preview" }));
    expect(panel).toHaveAttribute("data-layout", "floating");
    fireEvent.click(screen.getByRole("button", { name: "Collapse preview" }));
    expect(screen.queryByTestId("preview-draft")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Expand preview" })).toBeInTheDocument();
  });

  it("keeps the revision composer scoped to prose changes", () => {
    const onRevise = vi.fn();
    render(
      <ReportPreviewPanel
        value="Rewrite the limitations"
        onChange={vi.fn()}
        onRevise={onRevise}
        busy={false}
      >
        <div>Draft report</div>
      </ReportPreviewPanel>,
    );

    expect(screen.getByText(/source facts, results, and lineage remain read-only/i))
      .toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Revise draft" }));
    expect(onRevise).toHaveBeenCalledTimes(1);
  });
});
