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
  executionPolicy: "proposal_only",
  setExecutionPolicy: vi.fn(),
};

vi.mock("../../workbench/agent/AgentSurfaceContext", () => ({ useAgentSurfaceOptional: () => surface }));
vi.mock("../../workbench/agent/AgentCapabilityPopover", () => ({ AgentCapabilityPopover: () => <button type="button">Capabilities</button> }));

import { AgentColumnComposer, focusChipText } from "./AgentColumnComposer";

describe("AgentColumnComposer", () => {
  beforeEach(() => {
    surface.prompt = "";
    surface.isSubmitting = false;
    surface.sessionStatus = "idle";
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

  test("a restored running turn blocks Enter and retains Stop", () => {
    surface.sessionStatus = "running";
    surface.prompt = "Do not create a second turn";
    render(<AgentColumnComposer />);
    fireEvent.keyDown(screen.getByRole("textbox", { name: "Ask Agent" }), {key:"Enter"});
    expect(surface.sendPrompt).not.toHaveBeenCalled();
    expect(screen.getByRole("button", {name:"Stop Agent"})).toBeInTheDocument();
  });

  test("one mode control replaces the Mode select and the Review-first toggle", () => {
    render(<AgentColumnComposer />);
    expect(screen.queryByRole("button", { name: "Review first" })).not.toBeInTheDocument();
    expect(screen.queryByText("Every step waits for your OK")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /^Mode: Review every step/ }));
    fireEvent.click(screen.getByRole("radio", { name: /Run read-only analyses/ }));
    expect(surface.setExecutionPolicy).toHaveBeenCalledWith("auto_read_only");
  });

  test("Shift+Tab in the message box switches the mode", () => {
    surface.setExecutionPolicy.mockClear();
    render(<AgentColumnComposer />);
    fireEvent.keyDown(screen.getByRole("textbox", { name: "Ask Agent" }), { key: "Tab", shiftKey: true });
    expect(surface.setExecutionPolicy).toHaveBeenCalledWith("auto_read_only");
  });

  test("a message typed while the Agent works is queued, or steers when chosen; Stop stays", () => {
    const queue = vi.fn();
    Object.assign(surface, { queueTurnMessage: queue, isSubmitting: true, prompt: "Also report the median" });
    render(<AgentColumnComposer />);
    expect(screen.getByRole("button", { name: "Stop Agent" })).toBeInTheDocument();
    fireEvent.keyDown(screen.getByRole("textbox", { name: "Ask Agent" }), { key: "Enter" });
    expect(queue).toHaveBeenLastCalledWith("follow_up", "Also report the median");
    fireEvent.click(screen.getByRole("button", { name: "Steer" }));
    fireEvent.click(screen.getByRole("button", { name: "Steer the Agent" }));
    expect(queue).toHaveBeenLastCalledWith("steer", "Also report the median");
    expect(surface.sendPrompt).not.toHaveBeenCalled();
    delete (surface as Partial<typeof surface> & { queueTurnMessage?: unknown }).queueTurnMessage;
  });

  test("an unfinished turn is one banner with Resume", () => {
    const resumeTurn = vi.fn();
    Object.assign(surface, { durableTurns: [{ turn_id: "t1", status: "running", requires_reconcile: false }], resumeTurn });
    render(<AgentColumnComposer />);
    expect(screen.getByText("Previous turn unfinished")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Resume" }));
    expect(resumeTurn).toHaveBeenCalledWith("t1");
    Object.assign(surface, { durableTurns: [] });
  });
});
