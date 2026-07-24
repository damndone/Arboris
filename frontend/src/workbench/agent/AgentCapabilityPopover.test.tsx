import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AgentCapabilityPopover } from "./AgentCapabilityPopover";

const catalog = {
  capabilities: [
    {
      operation_id: "graph.fork",
      operation_version: "v1",
      effect_level: "mutation",
      scope: "current chain/node",
      scope_requirements: ["chain", "active_head"],
      risk_level: "mutating",
      confirmation_policy: "required",
      ui_description: "Create a new Chain branch from the current verified node.",
      example_prompts: ["Create a new branch from the current node."],
      natural_language_enabled: true,
    },
  ],
  boundary: {
    advisory: [{ id: "analysis.explain", label: "Compare results and explain diagnostics", description: "Read-only explanation." }],
    unsupported: [{ id: "data.cleaning", label: "Modify data-cleaning rules", description: "No typed operation is available." }],
  },
};

describe("AgentCapabilityPopover", () => {
  it("renders registry-backed executable, advisory, and unsupported boundaries", () => {
    render(<AgentCapabilityPopover catalog={catalog} onPromptSelect={() => {}} />);
    fireEvent.click(screen.getByTestId("agent-capability-trigger"));

    expect(screen.getByTestId("agent-capability-executable")).toHaveTextContent("graph.fork");
    expect(screen.getByTestId("agent-capability-executable")).toHaveTextContent("required");
    expect(screen.getByTestId("agent-capability-advisory")).toHaveTextContent("Compare results and explain diagnostics");
    expect(screen.getByTestId("agent-capability-unsupported")).toHaveTextContent("Modify data-cleaning rules");
    expect(screen.getByText("Use example")).toBeInTheDocument();
  });

  it("is honest when the capability projection is unavailable", () => {
    render(<AgentCapabilityPopover catalog={null} />);
    fireEvent.click(screen.getByTestId("agent-capability-trigger"));
    expect(screen.getByTestId("agent-capability-popover")).toHaveTextContent(
      "Capabilities unavailable",
    );
  });

  it("renders the open capabilities surface outside the Bottom panel clipping tree", () => {
    render(<AgentCapabilityPopover catalog={catalog} onPromptSelect={() => {}} />);
    fireEvent.click(screen.getByTestId("agent-capability-trigger"));

    const popover = screen.getByTestId("agent-capability-popover");
    expect(popover.parentElement).toBe(document.body);
    expect(popover).toHaveStyle({ position: "fixed" });
  });

  it("opens on hover and closes after the pointer leaves the trigger", async () => {
    render(<AgentCapabilityPopover catalog={catalog} onPromptSelect={() => {}} />);
    const trigger = screen.getByTestId("agent-capability-trigger");

    fireEvent.mouseEnter(trigger);
    expect(screen.getByTestId("agent-capability-popover")).toBeInTheDocument();

    fireEvent.mouseLeave(trigger);
    await waitFor(() => {
      expect(screen.queryByTestId("agent-capability-popover")).not.toBeInTheDocument();
    });
  });
});
