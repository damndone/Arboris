import { useState } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AgentComposer } from "./AgentComposer";
import { AgentPlanPanel } from "./AgentPlanPanel";
import { AgentColumnComposer } from "../../workspace/agent/AgentColumnComposer";
import { AgentSurfaceContext, type AgentSurfaceContextValue } from "./AgentSurfaceContext";
import { MessageActions } from "./transcript/MessageActions";
import { agentMessageFixture, llmModelFixture } from "../../apiFixtures";

type Composer = "graph" | "terminal" | "compact" | "column";
const composers: Composer[] = ["graph", "terminal", "compact", "column"];

function surface(overrides: Partial<AgentSurfaceContextValue> = {}): AgentSurfaceContextValue {
  return {
    messages: [
      agentMessageFixture({ entry_id: "u1", role: "user", content: "First question" }),
      agentMessageFixture({ entry_id: "u2", role: "user", content: "Latest question" }),
      agentMessageFixture({ entry_id: "a2", role: "assistant", content: "Response" }),
      agentMessageFixture({ entry_id: "local-u3", role: "user", content: "Not saved" }),
    ],
    prompt: "", setPrompt: vi.fn(), sendPrompt: vi.fn().mockResolvedValue(undefined),
    abortTurn: vi.fn().mockResolvedValue(undefined), isSubmitting: false, error: null,
    scopeLabel: "Current chain", contextUsedTokens: 0, contextWindowTokens: 32_000,
    contextPercent: 0, model: "deepseek-flash", modelOptions: [llmModelFixture({
      request_model: "deepseek-flash", display_name: "DeepSeek Flash", context_window_tokens: 32_000, supports_1m: false,
    })],
    setModel: vi.fn().mockResolvedValue(undefined), sessionStatus: "idle", activeOperation: null,
    proposals: [], confirmationBusyId: null, confirmProposal: vi.fn(), declineProposal: vi.fn(),
    reviseProposal: vi.fn(), forkFromMessage: vi.fn(), navigationLinks: [], hierarchy: null,
    eventCursor: 0, lastEventType: null, liveResponseText: "", sessionId: "session-a",
    executionMode: "ask", setExecutionMode: vi.fn(), executionPolicy: "proposal_only",
    setExecutionPolicy: vi.fn(), rewindTo: vi.fn().mockResolvedValue(undefined),
    queueTurnMessage: vi.fn().mockResolvedValue(undefined), approvePlan: vi.fn(),
    approveAndRunPlan: vi.fn(), continueTurn: vi.fn(),
    ...overrides,
  };
}

function composer(kind: Composer, onExpand = vi.fn()) {
  return kind === "column" ? <AgentColumnComposer /> : <AgentComposer variant={kind} onExpand={onExpand} />;
}

function mount(agent: AgentSurfaceContextValue, kind: Composer = "graph") {
  return render(<AgentSurfaceContext.Provider value={agent}>{composer(kind)}</AgentSurfaceContext.Provider>);
}

function enter() {
  fireEvent.keyDown(screen.getByRole("textbox", { name: "Ask Agent" }), { key: "Enter" });
}

afterEach(() => vi.restoreAllMocks());

describe("submitted Agent slash commands", () => {
  it.each(composers)("%s: /auto reuses mode selection only after submission", (kind) => {
    const agent = surface({ prompt: " /auto " });
    mount(agent, kind);
    expect(agent.setExecutionMode).not.toHaveBeenCalled();
    fireEvent.keyDown(screen.getByRole("textbox", { name: "Ask Agent" }), { key: "Enter", shiftKey: true });
    expect(agent.setExecutionMode).not.toHaveBeenCalled();
    enter();
    expect(agent.setExecutionMode).toHaveBeenCalledWith("auto");
    expect(agent.sendPrompt).not.toHaveBeenCalled();
    expect(agent.approvePlan).not.toHaveBeenCalled();
    expect(agent.approveAndRunPlan).not.toHaveBeenCalled();
    expect(agent.continueTurn).not.toHaveBeenCalled();
    expect(screen.getByText(/approve a plan before execution/i)).toBeInTheDocument();
  });

  it.each(composers)("%s: /ask restores both review settings", (kind) => {
    const agent = surface({ prompt: "/ask", executionMode: "auto", executionPolicy: "auto_read_only" });
    mount(agent, kind);
    enter();
    expect(agent.setExecutionMode).toHaveBeenCalledWith("ask");
    expect(agent.setExecutionPolicy).toHaveBeenCalledWith("proposal_only");
    expect(agent.sendPrompt).not.toHaveBeenCalled();
  });

  it.each(composers)("%s: /stop interrupts instead of queuing or sending", (kind) => {
    const agent = surface({ prompt: "/stop", sessionStatus: "running" });
    mount(agent, kind);
    enter();
    expect(agent.abortTurn).toHaveBeenCalledTimes(1);
    expect(agent.sendPrompt).not.toHaveBeenCalled();
    expect(agent.queueTurnMessage).not.toHaveBeenCalled();
  });

  it.each(composers)("%s: a running-turn command can also be submitted by button", (kind) => {
    const agent = surface({ prompt: "/plan", sessionStatus: "running", queueTurnMessage: undefined });
    mount(agent, kind);
    fireEvent.click(screen.getByRole("button", { name: "Run Agent command" }));
    expect(screen.getByText(/no analysis plan is available/i)).toBeInTheDocument();
    expect(agent.abortTurn).not.toHaveBeenCalled();
    expect(agent.sendPrompt).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Stop Agent" })).toBeInTheDocument();
  });

  it.each(composers)("%s: unknown commands are explicit and never become chat", (kind) => {
    const agent = surface({ prompt: "/unknown", sessionStatus: "running" });
    mount(agent, kind);
    enter();
    expect(screen.getByText(/unknown command.*\/unknown/i)).toBeInTheDocument();
    expect(agent.sendPrompt).not.toHaveBeenCalled();
    expect(agent.queueTurnMessage).not.toHaveBeenCalled();
    expect(agent.setPrompt).not.toHaveBeenCalled();
  });

  it.each(composers)("%s: /undo confirms before the last saved user message", async (kind) => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    const agent = surface({ prompt: "/undo" });
    mount(agent, kind);
    enter();
    expect(confirm).toHaveBeenCalledWith(expect.stringMatching(/original evidence is retained/i));
    expect(agent.rewindTo).not.toHaveBeenCalled();
    confirm.mockReturnValue(true);
    enter();
    await waitFor(() => expect(agent.rewindTo).toHaveBeenCalledWith("u2"));
    expect(agent.sendPrompt).not.toHaveBeenCalled();
  });

  it.each(["/auto", "/ask", "/undo"])("%s respects active-turn disabled controls", (prompt) => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    const agent = surface({ prompt, confirmationBusyId: "confirmation-a" });
    mount(agent);
    enter();
    expect(screen.getByText(/stop the current turn before/i)).toBeInTheDocument();
    expect(agent.setExecutionMode).not.toHaveBeenCalled();
    expect(agent.setExecutionPolicy).not.toHaveBeenCalled();
    expect(agent.rewindTo).not.toHaveBeenCalled();
    expect(confirm).not.toHaveBeenCalled();
    expect(agent.sendPrompt).not.toHaveBeenCalled();
  });

  it("rejects command arguments and unavailable controls without silently sending", () => {
    const agent = surface({ prompt: "/auto now", setExecutionMode: undefined });
    const view = mount(agent);
    enter();
    expect(screen.getByText(/does not take arguments/i)).toBeInTheDocument();
    view.rerender(<AgentSurfaceContext.Provider value={{ ...agent, prompt: "/auto" }}>{composer("graph")}</AgentSurfaceContext.Provider>);
    enter();
    expect(screen.getByText(/auto mode is not available/i)).toBeInTheDocument();
    expect(agent.sendPrompt).not.toHaveBeenCalled();
  });

  it("explains when there is no plan, saved message, or active turn", () => {
    const agent = surface({ prompt: "/plan", plan: null, messages: [] });
    const view = mount(agent);
    enter();
    expect(screen.getByText(/no analysis plan is available/i)).toBeInTheDocument();
    for (const [prompt, feedback] of [["/undo", /no saved user message/i], ["/stop", /no active turn/i]] as const) {
      view.rerender(<AgentSurfaceContext.Provider value={{ ...agent, prompt }}>{composer("graph")}</AgentSurfaceContext.Provider>);
      enter();
      expect(screen.getByText(feedback)).toBeInTheDocument();
    }
    expect(agent.sendPrompt).not.toHaveBeenCalled();
  });

  it("shows command request failures without a success claim", async () => {
    const agent = surface({ prompt: "/stop", sessionStatus: "running", abortTurn: vi.fn().mockRejectedValue(new Error("Cancellation unavailable")) });
    mount(agent);
    enter();
    expect(await screen.findByRole("alert")).toHaveTextContent("Cancellation unavailable");
  });

  it.each(composers)("%s: composition Enter never executes a command", (kind) => {
    const agent = surface({ prompt: "/auto" });
    mount(agent, kind);
    fireEvent.keyDown(screen.getByRole("textbox", { name: "Ask Agent" }), { key: "Enter", isComposing: true });
    expect(agent.setExecutionMode).not.toHaveBeenCalled();
    expect(agent.sendPrompt).not.toHaveBeenCalled();
  });

  it.each(composers)("%s: /plan opens and focuses the real plan without approving it", async (kind) => {
    const onExpand = vi.fn();
    const agent = surface({ prompt: "/plan", plan: {
      plan_id: "plan-a", version: 3, status: "draft", question: "Actual plan question", criteria: [],
      steps: [], approved_version: null, approved_at: null, allowed_classes: [], budget: {}, updated_at: "today",
    } });
    function Harness() {
      const [planViewRequest, setPlanViewRequest] = useState(0);
      return <AgentSurfaceContext.Provider value={{ ...agent, planViewRequest, showPlan: () => setPlanViewRequest(value => value + 1) }}>
        <AgentPlanPanel />{composer(kind, onExpand)}
      </AgentSurfaceContext.Provider>;
    }
    render(<Harness />);
    enter();
    const panel = screen.getByLabelText("Analysis plan");
    await waitFor(() => expect(panel).toHaveAttribute("open"));
    expect(panel.querySelector("summary")).toHaveFocus();
    expect(agent.approvePlan).not.toHaveBeenCalled();
    expect(agent.sendPrompt).not.toHaveBeenCalled();
    if (kind === "compact") expect(onExpand).toHaveBeenCalledTimes(1);
  });

  it("the existing rewind button uses the same confirmation boundary", () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    const rewind = vi.fn();
    render(<MessageActions message={agentMessageFixture({ entry_id: "u1", role: "user", content: "Analyze the data." })} pinned={false} busy={false} onRewind={rewind} />);
    fireEvent.click(screen.getByRole("button", { name: "Rewind to here" }));
    expect(confirm).toHaveBeenCalledWith(expect.stringMatching(/original evidence is retained/i));
    expect(rewind).not.toHaveBeenCalled();
  });
});
