import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { AgentComposer } from "./AgentComposer";
import {
  AgentSurfaceContext,
  type AgentSurfaceContextValue,
} from "./AgentSurfaceContext";

function value(overrides: Partial<AgentSurfaceContextValue> = {}): AgentSurfaceContextValue {
  return {
    messages: [],
    prompt: "",
    setPrompt: vi.fn(),
    sendPrompt: vi.fn(),
    isSubmitting: false,
    error: null,
    scopeLabel: "Current chain",
    contextUsedTokens: 2_048,
    contextWindowTokens: 32_000,
    contextPercent: 6.4,
    model: "deepseek-v4-flash",
    modelOptions: [
      { display_name: "DeepSeek V4 Flash", request_model: "deepseek-v4-flash", context_window_tokens: 32_000, supports_1m: false },
      { display_name: "DeepSeek Chat", request_model: "deepseek-chat", context_window_tokens: 64_000, supports_1m: false },
    ],
    setModel: vi.fn(),
    sessionStatus: "idle",
    activeOperation: null,
    proposals: [],
    confirmationBusyId: null,
    confirmProposal: vi.fn(),
    declineProposal: vi.fn(),
    reviseProposal: vi.fn(),
    forkFromMessage: vi.fn(),
    navigationLinks: [],
    hierarchy: null,
    eventCursor: 0,
    lastEventType: null,
    ...overrides,
  };
}

function mount(context: AgentSurfaceContextValue) {
  return render(
    <AgentSurfaceContext.Provider value={context}>
      <AgentComposer />
    </AgentSurfaceContext.Provider>,
  );
}

describe("AgentComposer", () => {
  it("renders the bounded context ring and synchronized model selector", () => {
    mount(value());

    expect(screen.getByTestId("agent-composer")).toBeInTheDocument();
    expect(screen.getByTestId("agent-context-ring")).toHaveAccessibleName(
      /2,048.*32,000/i,
    );
    expect(screen.getByRole("listbox", { name: "Agent model" })).toHaveValue(
      "deepseek-v4-flash",
    );
    expect(screen.getByRole("textbox", { name: "Ask Agent" })).toHaveAttribute(
      "placeholder",
      "Ask about the current analysis or request a typed change and rerun",
    );
  });

  it("opens the registry-backed capability boundary", () => {
    mount(value({
      capabilityCatalog: {
        capabilities: [],
        boundary: {
          advisory: [{ id: "a", label: "Compare results", description: "Read-only explanation" }],
          unsupported: [{ id: "u", label: "Arbitrary file operations", description: "Not supported" }],
        },
      },
    }));
    fireEvent.click(screen.getByTestId("agent-capability-trigger"));
    expect(screen.getByTestId("agent-capability-advisory")).toHaveTextContent("Compare results");
    expect(screen.getByTestId("agent-capability-unsupported")).toHaveTextContent("Arbitrary file operations");
  });

  it("turns an executable capability example into an editable prompt", () => {
    const context = value({
      capabilityCatalog: {
        capabilities: [{
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
        }],
        boundary: { advisory: [], unsupported: [] },
      },
    });
    mount(context);

    fireEvent.click(screen.getByTestId("agent-capability-trigger"));
    fireEvent.click(screen.getByTestId("agent-capability-use-graph.fork"));

    expect(context.setPrompt).toHaveBeenCalledWith(
      "Create a new branch from the current node.",
    );
    expect(context.sendPrompt).not.toHaveBeenCalled();
    expect(screen.queryByTestId("agent-capability-popover")).not.toBeInTheDocument();
  });

  it("styles the bar with theme-token classes instead of hardcoded dark surfaces", () => {
    mount(value());

    const bar = screen.getByTestId("agent-composer");
    expect(bar.className).toContain("wb-agent-composer");
    // The ring and model selector live INSIDE the bar (integrated, not floating).
    expect(bar).toContainElement(screen.getByTestId("agent-context-ring"));
    expect(bar).toContainElement(screen.getByRole("listbox", { name: "Agent model" }));
    // No inline hardcoded dark fallback surface left on the container.
    expect(bar.getAttribute("style") ?? "").not.toMatch(/#202124/);
  });

  it("submits on Enter but keeps Shift+Enter for multiline prompts", () => {
    const context = value({ prompt: "inspect the active head" });
    mount(context);
    const input = screen.getByRole("textbox", { name: "Ask Agent" });

    fireEvent.keyDown(input, { key: "Enter", shiftKey: true });
    expect(context.sendPrompt).not.toHaveBeenCalled();
    fireEvent.keyDown(input, { key: "Enter" });
    expect(context.sendPrompt).toHaveBeenCalledWith("inspect the active head");
  });

  it("shows a visible error and disables submission while the turn is running", () => {
    mount(
      value({
        isSubmitting: true,
        error: "LLM upstream is unavailable",
      }),
    );

    expect(screen.getByRole("status")).toHaveTextContent("Thinking");
    expect(screen.getByRole("alert")).toHaveTextContent("LLM upstream is unavailable");
    expect(screen.getByRole("button", { name: "Send to Agent" })).toBeDisabled();
  });

  it("opens a usable context popover from a true circular control", () => {
    mount(value());

    const ring = screen.getByTestId("agent-context-ring");
    expect(ring).toHaveAttribute("aria-haspopup", "dialog");
    expect(ring).toHaveAttribute("aria-expanded", "false");
    expect(ring).toHaveStyle({ aspectRatio: "1 / 1" });
    expect(ring).toHaveStyle({
      width: "30px",
      height: "30px",
      minWidth: "30px",
      minHeight: "30px",
    });

    fireEvent.click(ring);

    expect(ring).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByTestId("agent-context-popover")).toHaveTextContent("2,048");
    expect(screen.getByTestId("agent-context-popover")).toHaveTextContent("32,000");
    expect(screen.getByTestId("agent-context-popover")).toHaveTextContent(/remaining/i);
  });

  it("opens context details on hover and closes them when the pointer leaves", () => {
    mount(value());

    const ring = screen.getByTestId("agent-context-ring");
    const control = ring.parentElement as HTMLElement;
    fireEvent.mouseEnter(control);
    expect(screen.getByTestId("agent-context-popover")).toBeInTheDocument();

    fireEvent.mouseLeave(control);
    expect(screen.queryByTestId("agent-context-popover")).not.toBeInTheDocument();
  });

  it("shows remaining and total context beside the ring without requiring a click", () => {
    mount(value());

    const summary = screen.getByTestId("agent-context-summary");
    expect(summary).toHaveTextContent("29,952");
    expect(summary).toHaveTextContent("32,000");
    expect(summary).toHaveTextContent(/remaining/i);
    expect(screen.getByTestId("agent-context-ring")).toHaveAttribute("aria-valuemax", "32000");
  });
});
