import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, test, vi } from "vitest";

const surface = {
  abortTurn: vi.fn(),
  capabilityCatalog: null,
  contextUsedTokens: 1200,
  contextWindowTokens: 64000,
  error: null as string | null,
  isSubmitting: false,
  model: "deepseek-flash",
  modelOptions: [{ request_model: "deepseek-flash", display_name: "DeepSeek V4.1 Flash" }],
  prompt: "",
  scopeLabel: "Current chain · ols_robust (primary)",
  sendPrompt: vi.fn(),
  sessionStatus: "idle",
  setModel: vi.fn(),
  setPrompt: vi.fn(),
};

vi.mock("../../workbench/agent/AgentSurfaceContext", () => ({ useAgentSurfaceOptional: () => surface }));
vi.mock("../../workbench/agent/AgentCapabilityPopover", () => ({ AgentCapabilityPopover: () => <button type="button">Capabilities</button> }));

import { AgentColumnComposer, focusChipText } from "./AgentColumnComposer";

describe("AgentColumnComposer", () => {
  beforeEach(() => {
    surface.prompt = "";
    surface.isSubmitting = false;
    surface.sendPrompt.mockClear();
  });

  test("names what the Agent is about in reader terms", () => {
    expect(focusChipText("Global Agent · 2 runs · 1 families")).toBe("Whole project");
    expect(focusChipText("Current chain · ols_robust (primary)")).toBe("ols_robust (primary)");
    render(<AgentColumnComposer />);
    expect(screen.getByText("ols_robust (primary)")).toBeInTheDocument();
  });

  test("Enter sends, Shift+Enter does not, and an empty message cannot be sent", () => {
    const { rerender } = render(<AgentColumnComposer />);
    expect(screen.getByRole("button", { name: "Send to Agent" })).toBeDisabled();
    surface.prompt = "Is educ = 1?";
    rerender(<AgentColumnComposer />);
    fireEvent.keyDown(screen.getByRole("textbox", { name: "Ask Agent" }), { key: "Enter", shiftKey: true });
    expect(surface.sendPrompt).not.toHaveBeenCalled();
    fireEvent.keyDown(screen.getByRole("textbox", { name: "Ask Agent" }), { key: "Enter" });
    expect(surface.sendPrompt).toHaveBeenCalledWith("Is educ = 1?");
  });

  test("while the Agent works, send becomes stop; no dead controls are shown", () => {
    surface.isSubmitting = true;
    render(<AgentColumnComposer />);
    fireEvent.click(screen.getByRole("button", { name: "Stop Agent" }));
    expect(surface.abortTurn).toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Voice input" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add context" })).not.toBeInTheDocument();
  });
});
