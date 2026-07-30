import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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
    abortTurn: vi.fn(),
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
    liveResponseText: "",
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
  it("does not render an idle-only session label", () => {
    mount(value({ sessionStatus: "idle" }));

    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.queryByText(/^idle$/i)).not.toBeInTheDocument();
  });

  it("keeps the compact composer interactive and expands only from its disclosure control", () => {
    const context = value({ prompt: "inspect the active head" });
    const onExpand = vi.fn();
    render(
      <AgentSurfaceContext.Provider value={context}>
        <AgentComposer variant="compact" onExpand={onExpand} />
      </AgentSurfaceContext.Provider>,
    );

    const compactComposer = screen.getByTestId("agent-compact-composer");
    const input = screen.getByRole("textbox", { name: "Ask Agent" });
    expect(compactComposer).toContainElement(input);
    expect(compactComposer).toContainElement(screen.getByTestId("agent-context-ring"));
    expect(screen.getByRole("listbox", { name: "Agent model" })).toBeInTheDocument();
    expect(compactComposer).not.toContainElement(
      screen.getByRole("button", { name: "Expand Agent panel" }),
    );

    fireEvent.change(input, { target: { value: "compare the active models" } });
    fireEvent.keyDown(input, { key: "Enter" });
    fireEvent.change(screen.getByRole("listbox", { name: "Agent model" }), {
      target: { value: "deepseek-chat" },
    });

    expect(context.setPrompt).toHaveBeenCalledWith("compare the active models");
    expect(context.sendPrompt).toHaveBeenCalledWith("inspect the active head");
    expect(context.setModel).toHaveBeenCalledWith("deepseek-chat");
    expect(onExpand).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Expand Agent panel" }));

    expect(onExpand).toHaveBeenCalledTimes(1);
  });

  it("keeps compact turn activity outside the input bar until the user opens it", () => {
    const context = value({
      isSubmitting: true,
      sessionStatus: "running",
      lastEventType: "tool_call",
      activeTurnStartedAt: Date.now() - 4_000,
    });
    const onExpand = vi.fn();
    render(
      <AgentSurfaceContext.Provider value={context}>
        <AgentComposer variant="compact" onExpand={onExpand} />
      </AgentSurfaceContext.Provider>,
    );

    const activity = screen.getByRole("button", { name: "View Agent activity" });
    expect(activity).toHaveTextContent(/working/i);
    expect(activity).toHaveTextContent(/checking evidence/i);
    expect(screen.getByTestId("agent-compact-composer")).not.toContainElement(activity);

    fireEvent.click(activity);

    expect(onExpand).toHaveBeenCalledTimes(1);
  });

  it("keeps a sent compact prompt collapsed and then reports its completion", async () => {
    const onExpand = vi.fn();
    const initialContext = value({ prompt: "summarize the active model" });
    const rendered = render(
      <AgentSurfaceContext.Provider value={initialContext}>
        <AgentComposer variant="compact" onExpand={onExpand} />
      </AgentSurfaceContext.Provider>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Send to Agent" }));
    expect(initialContext.sendPrompt).toHaveBeenCalledWith("summarize the active model");
    expect(onExpand).not.toHaveBeenCalled();

    rendered.rerender(
      <AgentSurfaceContext.Provider value={value({
        prompt: "",
        isSubmitting: true,
        sessionStatus: "running",
        activeTurnStartedAt: Date.now() - 1_000,
      })}>
        <AgentComposer variant="compact" onExpand={onExpand} />
      </AgentSurfaceContext.Provider>,
    );
    expect(screen.getByRole("button", { name: "View Agent activity" })).toHaveTextContent(/working/i);

    rendered.rerender(
      <AgentSurfaceContext.Provider value={value({ prompt: "" })}>
        <AgentComposer variant="compact" onExpand={onExpand} />
      </AgentSurfaceContext.Provider>,
    );

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "View Agent activity" })).toHaveTextContent(/processed/i);
    });
    expect(onExpand).not.toHaveBeenCalled();
  });

  it("renders the bounded context ring and synchronized model selector", () => {
    mount(value());

    expect(screen.getByTestId("agent-composer")).toBeInTheDocument();
    expect(screen.getByTestId("agent-context-ring")).toHaveAccessibleName(
      /29,952 tokens remaining out of 32,000/i,
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

  it("shows a visible error and replaces submission with stopping while the turn is running", () => {
    mount(
      value({
        isSubmitting: true,
        error: "LLM upstream is unavailable",
      }),
    );

    expect(screen.getByRole("status")).toHaveTextContent("Thinking");
    expect(screen.getByRole("alert")).toHaveTextContent("LLM upstream is unavailable");
    expect(screen.queryByRole("button", { name: "Send to Agent" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Stop Agent" })).toBeEnabled();
  });

  it("offers an explicit stop control while a provider turn is running", () => {
    const abortTurn = vi.fn();
    mount({
      ...value({ isSubmitting: true }),
      abortTurn,
    } as AgentSurfaceContextValue);

    const stop = screen.getByRole("button", { name: "Stop Agent" });
    expect(stop).toBeEnabled();
    fireEvent.click(stop);
    expect(abortTurn).toHaveBeenCalledTimes(1);
  });

  it("renders a hollow ring whose progress arc uses a round linecap and does not resize", () => {
    mount(value());

    const ring = screen.getByTestId("agent-context-ring");
    const progress = ring.querySelector(".wb-context-ring-progress") as SVGCircleElement;
    // Hollow ring, not a filled pie: the arc is a stroked circle with no fill.
    expect(progress).toHaveAttribute("fill", "none");
    expect(progress).toHaveAttribute("stroke-linecap", "round");
    // Fixed geometry -> the SVG box is constant regardless of progress.
    expect(ring.querySelector("svg")).toHaveAttribute("width", "20");
    expect(ring.querySelector("svg")).toHaveAttribute("height", "20");
  });

  it("reveals used / remaining / total only in a hover tooltip, not inline", () => {
    mount(value());

    // No always-on summary text beside the ring anymore.
    expect(screen.queryByTestId("agent-context-summary")).not.toBeInTheDocument();

    const ring = screen.getByTestId("agent-context-ring");
    expect(screen.queryByTestId("agent-context-tooltip")).not.toBeInTheDocument();

    fireEvent.mouseEnter(ring);
    const tooltip = screen.getByTestId("agent-context-tooltip");
    expect(tooltip).toHaveTextContent("2,048"); // used
    expect(tooltip).toHaveTextContent("29,952"); // remaining
    expect(tooltip).toHaveTextContent("32,000"); // total

    fireEvent.mouseLeave(ring);
    expect(screen.queryByTestId("agent-context-tooltip")).not.toBeInTheDocument();
  });
});
