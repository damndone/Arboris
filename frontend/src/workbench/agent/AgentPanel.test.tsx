import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { AgentPanel } from "./AgentPanel";
import {
  AgentSurfaceContext,
  type AgentSurfaceContextValue,
} from "./AgentSurfaceContext";
import type { AgentHierarchyNode, AgentNavigationRef } from "./agentTypes";

function value(overrides: Partial<AgentSurfaceContextValue> = {}): AgentSurfaceContextValue {
  return {
    messages: [
      { entry_id: "u1", role: "user", content: "检查 active head", stop_reason: null },
      { entry_id: "a1", role: "assistant", content: "发现一个待确认的风险。", stop_reason: "stop" },
    ],
    prompt: "",
    setPrompt: vi.fn(),
    sendPrompt: vi.fn(),
    abortTurn: vi.fn(),
    isSubmitting: false,
    error: null,
    scopeLabel: "Current chain · run-a",
    contextUsedTokens: 2_048,
    contextWindowTokens: 32_000,
    contextPercent: 6.4,
    model: "deepseek-v4-flash",
    modelOptions: [{ display_name: "DeepSeek V4 Flash", request_model: "deepseek-v4-flash", context_window_tokens: 32_000, supports_1m: false }],
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

describe("AgentPanel — sandboxed program output", () => {
  const codeOperation = {
    record_id: "oprec_code_1",
    operation_id: "code.execute",
    status: "completed",
    target_run_id: null,
    stdout: "wage mean: 34.5\nrows in: 30\n",
    postEstimationResults: [],
    diff_ref: null,
    verification: { passed: true },
    diffFocused: false,
  };

  it("shows what the sandboxed code printed, in the terminal panel", () => {
    render(
      <AgentSurfaceContext.Provider value={value({ activeOperation: codeOperation })}>
        <AgentPanel runId="run-a" projectRoot="/proj" />
      </AgentSurfaceContext.Provider>,
    );

    const stdout = screen.getByTestId("agent-operation-stdout");
    expect(stdout).toHaveTextContent("wage mean: 34.5");
    expect(stdout).toHaveTextContent("rows in: 30");
    expect(screen.getByTestId("agent-operation-status")).toHaveTextContent(
      "code.execute → completed",
    );
  });

  it("renders no stdout line for operations that printed nothing", () => {
    render(
      <AgentSurfaceContext.Provider
        value={value({ activeOperation: { ...codeOperation, stdout: null } })}
      >
        <AgentPanel runId="run-a" projectRoot="/proj" />
      </AgentSurfaceContext.Provider>,
    );

    expect(screen.queryByTestId("agent-operation-stdout")).toBeNull();
  });
});

describe("AgentPanel — declared post-estimation results", () => {
  const workflowOperation = {
    record_id: "oprec_workflow_1",
    operation_id: "operation.multi_step",
    status: "completed",
    target_run_id: "run-child",
    stdout: null,
    postEstimationResults: [
      {
        artifact_id: "workflow_model_quadratic_stationary_point_abc",
        artifact_type: "post_estimation",
        operation_id: "model.quadratic_stationary_point",
        run_id: "run-source",
        model_run_id: "run-child",
        workflow_id: "wf-1",
        workflow_step_id: "stationary_point",
        result: {
          schema_version: "workbench.model.quadratic-stationary-point/v1",
          column: "experience",
          stationary_point: 211.59338521178753,
          stationary_point_within_observed_range: false,
        },
      },
    ],
    diff_ref: null,
    verification: { passed: true },
    diffFocused: false,
  };

  it("answers the question in the transcript instead of only reporting completion", () => {
    render(
      <AgentSurfaceContext.Provider value={value({ activeOperation: workflowOperation })}>
        <AgentPanel runId="run-a" projectRoot="/proj" />
      </AgentSurfaceContext.Provider>,
    );

    const results = screen.getByTestId("agent-operation-post-estimation");
    expect(results).toHaveTextContent("Quadratic stationary point");
    expect(results).toHaveTextContent("stationary point: 211.5934");
    // The out-of-range flag is what separates a number from a claim.
    expect(results).toHaveTextContent("stationary point within observed range: no");
    expect(results).not.toHaveTextContent("workbench.model.quadratic");
  });

  it("renders no result line when the operation declared none", () => {
    render(
      <AgentSurfaceContext.Provider
        value={value({
          activeOperation: { ...workflowOperation, postEstimationResults: [] },
        })}
      >
        <AgentPanel runId="run-a" projectRoot="/proj" />
      </AgentSurfaceContext.Provider>,
    );

    expect(screen.queryByTestId("agent-operation-post-estimation")).toBeNull();
  });
});

describe("AgentPanel", () => {
  it("shows elapsed time and observable activity without a private-reasoning banner", () => {
    render(
      <AgentSurfaceContext.Provider value={value({
        isSubmitting: true,
        activeTurnStartedAt: Date.now() - 4_000,
        lastEventType: "tool_call",
      })}>
        <AgentPanel runId="run-a" projectRoot="/proj" />
      </AgentSurfaceContext.Provider>,
    );

    expect(screen.getByTestId("agent-turn-progress")).toHaveTextContent(/Working · 4s/);
    expect(screen.queryByText(/private reasoning is not displayed/i)).not.toBeInTheDocument();
    expect(screen.getByTestId("agent-execution-trace")).toHaveTextContent("Checking evidence");
  });

  it("shows an actionable provider failure without leaving the turn marked as working", () => {
    render(
      <AgentSurfaceContext.Provider value={value({
        sessionStatus: "failed",
        messages: [
          { entry_id: "u1", role: "user", content: "Prepare a workflow", stop_reason: null },
          { entry_id: "a1", role: "assistant", content: "", stop_reason: "error", error: "LLMUpstreamError" },
        ],
      })}>
        <AgentPanel runId="run-a" projectRoot="/proj" />
      </AgentSurfaceContext.Provider>,
    );

    expect(screen.queryByTestId("agent-turn-progress")).toBeNull();
    expect(screen.getByTestId("agent-turn-error")).toHaveTextContent(
      "The configured provider did not return a usable response",
    );
    expect(screen.getByTestId("agent-turn-error")).toHaveTextContent(
      "No proposal or analysis was executed",
    );
  });

  it("keeps a historical step-budget stop accurate when a proposal is pending", () => {
    render(
      <AgentSurfaceContext.Provider value={value({
        sessionStatus: "blocked",
        messages: [
          { entry_id: "u1", role: "user", content: "Prepare a workflow", stop_reason: null },
          { entry_id: "a1", role: "assistant", content: "", stop_reason: "error", error: "max_steps_exceeded" },
        ],
        proposals: [{
          record_type: "revision",
          proposal_id: "proposal-1",
          operation_id: "operation.multi_step",
          operation_version: "v1",
          revision: 1,
          session_id: "session-a",
          chain_id: "chain-a",
          command_id: "command-a",
          target: {},
          preconditions: {},
          changes: { steps: [] },
          evidence_refs: [],
          expected_effect: [],
          risks: [],
          created_at: "2026-07-30T00:00:00Z",
          fingerprint: "sha256:test",
          status: "pending",
        }],
      })}>
        <AgentPanel runId="run-a" projectRoot="/proj" />
      </AgentSurfaceContext.Provider>,
    );

    expect(screen.getByTestId("agent-turn-error")).toHaveTextContent(
      "proposal that is still awaiting your review",
    );
    expect(screen.getByTestId("agent-turn-error")).toHaveTextContent(
      "will not execute automatically",
    );
    expect(screen.getByTestId("agent-turn-error")).not.toHaveTextContent(
      "No proposal or analysis was executed",
    );
  });

  it("renders the durable transcript and scope/context summary", () => {
    render(
      <AgentSurfaceContext.Provider value={value()}>
        <AgentPanel runId="run-a" projectRoot="/proj" />
      </AgentSurfaceContext.Provider>,
    );

    expect(screen.getByTestId("agent-panel")).toBeInTheDocument();
    expect(screen.getByText("检查 active head")).toBeInTheDocument();
    expect(screen.getByText("发现一个待确认的风险。")).toBeInTheDocument();
    expect(screen.getByText(/Current chain · run-a/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Session status: idle")).not.toBeInTheDocument();
    // Context usage is a hollow ring; the token figures live in its aria-label
    // (and hover tooltip), not as inline summary text.
    expect(screen.getByTestId("agent-context-ring")).toHaveAccessibleName(
      /remaining out of 32,000/i,
    );
  });

  it("renders the transcript as a terminal log with role prompt markers", () => {
    render(
      <AgentSurfaceContext.Provider value={value()}>
        <AgentPanel runId="run-a" projectRoot="/proj" />
      </AgentSurfaceContext.Provider>,
    );

    const log = screen.getByRole("log", { name: /Agent transcript/ });
    expect(log.className).toContain("wb-agent-terminal");
    const userLine = screen.getByTestId("agent-message-user");
    const agentLine = screen.getByTestId("agent-message-assistant");
    // Terminal form: prompt-marker prefix on the user line, plain output for
    // the agent line — no chat bubbles.
    expect(userLine).toHaveTextContent("❯");
    expect(userLine.className).toContain("wb-agent-terminal-line");
    expect(agentLine.className).toContain("wb-agent-terminal-line");
  });

  it("follows newly appended output only while the transcript is at its bottom", () => {
    const initial = value({
      isSubmitting: true,
      messages: [{ entry_id: "u1", role: "user", content: "检查结果", stop_reason: null }],
    });
    const { rerender } = render(
      <AgentSurfaceContext.Provider value={initial}>
        <AgentPanel runId="run-a" projectRoot="/proj" />
      </AgentSurfaceContext.Provider>,
    );
    const transcript = screen.getByRole("log", { name: /Agent transcript/ }) as HTMLDivElement;
    Object.defineProperties(transcript, {
      clientHeight: { configurable: true, value: 100 },
      scrollHeight: { configurable: true, value: 500 },
    });
    transcript.scrollTop = 400;
    fireEvent.scroll(transcript);

    Object.defineProperty(transcript, "scrollHeight", { configurable: true, value: 620 });
    rerender(
      <AgentSurfaceContext.Provider value={value({
        isSubmitting: true,
        messages: [
          ...initial.messages,
          { entry_id: "a1", role: "assistant", content: "这是最新输出。", stop_reason: "stop" },
        ],
      })}>
        <AgentPanel runId="run-a" projectRoot="/proj" />
      </AgentSurfaceContext.Provider>,
    );
    expect(transcript.scrollTop).toBe(620);

    transcript.scrollTop = 180;
    fireEvent.scroll(transcript);
    Object.defineProperty(transcript, "scrollHeight", { configurable: true, value: 740 });
    rerender(
      <AgentSurfaceContext.Provider value={value({
        isSubmitting: true,
        messages: [
          ...initial.messages,
          { entry_id: "a1", role: "assistant", content: "这是最新输出。\n\n补充说明。", stop_reason: "stop" },
        ],
      })}>
        <AgentPanel runId="run-a" projectRoot="/proj" />
      </AgentSurfaceContext.Provider>,
    );
    expect(transcript.scrollTop).toBe(180);
  });

  it("groups a tool-assisted turn into a collapsible reasoning trace", () => {
    const withReasoning = value({
      messages: [
        { entry_id: "u1", role: "user", content: "检查模型结果", stop_reason: null },
        {
          entry_id: "a1",
          role: "assistant",
          content: "我会先核对模型和诊断证据。",
          stop_reason: "tool_calls",
        },
        {
          entry_id: "t1",
          role: "tool",
          name: "inspect_model_result",
          content: JSON.stringify({ ok: true, output: { result_id: "result-1" } }),
          stop_reason: null,
        },
        {
          entry_id: "a2",
          role: "assistant",
          content: "模型结果已核对：系数为正。",
          stop_reason: "stop",
        },
      ],
    });

    render(
      <AgentSurfaceContext.Provider value={withReasoning}>
        <AgentPanel runId="run-a" projectRoot="/proj" />
      </AgentSurfaceContext.Provider>,
    );

    const reasoning = screen.getByTestId("agent-reasoning-u1");
    expect(reasoning).toHaveTextContent("Reasoning");
    expect(reasoning).toHaveTextContent("2 steps");
    expect(reasoning).toHaveTextContent("我会先核对模型和诊断证据。");
    expect(reasoning).toHaveTextContent("inspect_model_result ✓ ok");
    expect(reasoning).not.toContainElement(screen.getByText("模型结果已核对：系数为正。"));
  });

  it("leaves hierarchy browsing to AI activity so the terminal owns the panel space", () => {
    const rootRef: AgentNavigationRef = {
      kind: "agent_session",
      id: "agent-main",
      label: "Agent agent_main",
      relation: "context",
      available: true,
      href: { view: "agent", session_id: "agent-main" },
    };
    const hierarchy: AgentHierarchyNode = {
      ref: rootRef,
      status: "idle",
      children: [],
    };

    render(
      <AgentSurfaceContext.Provider
        value={value({ hierarchy, navigationLinks: [rootRef] })}
      >
        <AgentPanel runId="run-a" projectRoot="/proj" />
      </AgentSurfaceContext.Provider>,
    );

    expect(screen.queryByTestId("agent-context-details")).not.toBeInTheDocument();
    expect(screen.queryByText("Agent context")).not.toBeInTheDocument();
    expect(screen.getByRole("log", { name: /Agent transcript/ })).toBeInTheDocument();
  });

  it("offers a typed fork action on a message with a verified source node", () => {
    const forkFromMessage = vi.fn().mockResolvedValue(true);
    const openNavigation = vi.fn();
    const withMessageLink = value({ forkFromMessage, openNavigation });
    withMessageLink.messages = [{
      entry_id: "u1",
      role: "user",
      content: "从这个节点继续探索",
      stop_reason: null,
      navigation: [{
        kind: "graph_node",
        id: "run-a::model:ols_1",
        label: "Source model:ols_1",
        relation: "source",
        available: true,
        href: {
          view: "graph",
          run_id: "run-a",
          node_ref: "model:ols_1",
          forest_node_key: "run-a::model:ols_1",
        },
      }],
    }];

    render(
      <AgentSurfaceContext.Provider value={withMessageLink}>
        <AgentPanel runId="run-a" projectRoot="/proj" />
      </AgentSurfaceContext.Provider>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Fork from Agent message u1" }));
    expect(forkFromMessage).toHaveBeenCalledWith(
      "u1",
      expect.objectContaining({ kind: "graph_node", id: "run-a::model:ols_1" }),
    );
  });

  it("projects tool messages as typed status lines, not raw JSON dumps", () => {
    const withTool = value();
    withTool.messages = [
      { entry_id: "u1", role: "user", content: "检查节点", stop_reason: null },
      {
        entry_id: "t1",
        role: "tool",
        name: "inspect_node_context",
        content: JSON.stringify({
          error: null,
          ok: true,
          output: { context_version: "node-operation-context/v1", owner_run_id: "run-a" },
        }),
        stop_reason: null,
      },
      {
        entry_id: "t2",
        role: "tool",
        name: "propose_operation",
        content: JSON.stringify({
          error: null,
          ok: true,
          output: { requires_confirmation: true, proposal: { proposal_id: "p-1" } },
        }),
        stop_reason: null,
      },
      {
        entry_id: "t3",
        role: "tool",
        name: "inspect_diagnostics",
        content: JSON.stringify({
          output: null,
          ok: false,
          error: "tool_runtime_error",
        }),
        stop_reason: null,
      },
    ];
    render(
      <AgentSurfaceContext.Provider value={withTool}>
        <AgentPanel runId="run-a" projectRoot="/proj" />
      </AgentSurfaceContext.Provider>,
    );

    const toolLines = screen.getAllByTestId("agent-message-tool");
    expect(toolLines[0]).toHaveTextContent("inspect_node_context");
    expect(toolLines[0]).toHaveTextContent("ok");
    expect(toolLines[0]).not.toHaveTextContent("node-operation-context/v1");
    expect(toolLines[1]).toHaveTextContent(/proposal ready/i);
    expect(toolLines[1]).toHaveTextContent("p-1");
    expect(toolLines[2]).toHaveTextContent("inspect_diagnostics");
    expect(toolLines[2]).toHaveTextContent("tool_runtime_error");
  });

  it("keeps an explicit empty state when no turn has started", () => {
    render(
      <AgentSurfaceContext.Provider value={{ ...value(), messages: [] }}>
        <AgentPanel runId="run-a" projectRoot="/proj" />
      </AgentSurfaceContext.Provider>,
    );
    expect(screen.getByTestId("agent-empty")).toHaveTextContent("Start a task");
  });

  it("renders a pending proposal as an explicit confirmation card", () => {
    const withProposal = value();
    withProposal.proposals = [{
      record_type: "revision",
      proposal_id: "proposal-1",
      operation_id: "model.rerun",
      operation_version: "v1",
      revision: 1,
      session_id: "session-1",
      chain_id: "chain-a",
      command_id: null,
      target: { run_id: "run-a", node_ref: "model:ols_1" },
      preconditions: { active_head_run_id: "run-a" },
      changes: { covariance: { old: "nonrobust", new: "HC1" } },
      evidence_refs: ["diagnostic:warning"],
      expected_effect: ["standard errors may change"],
      risks: ["small samples"],
      created_at: "2026-07-14T00:00:00Z",
      fingerprint: "fingerprint-1",
      status: "pending",
    }];
    render(
      <AgentSurfaceContext.Provider value={withProposal}>
        <AgentPanel runId="run-a" projectRoot="/proj" />
      </AgentSurfaceContext.Provider>,
    );

    expect(screen.getByTestId("agent-action-rail")).toHaveTextContent("HC1");
    expect(screen.getByTestId("agent-proposal-proposal-1")).toHaveTextContent("HC1");
    expect(screen.getByRole("button", { name: "Confirm proposal proposal-1" })).toBeInTheDocument();
  });

  it("renders object-valued model options literally instead of mistaking them for a diff", () => {
    const withProposal = value();
    withProposal.proposals = [{
      record_type: "revision",
      proposal_id: "proposal-model-options",
      operation_id: "model.rerun",
      operation_version: "v1",
      revision: 1,
      session_id: "session-1",
      chain_id: "chain-a",
      command_id: null,
      target: { run_id: "run-a", node_ref: "model:future_1" },
      preconditions: { active_head_run_id: "run-a" },
      changes: {
        model_options: {
          old: { nested: true },
          new: ["a legitimate future option value"],
          additional_option: true,
        },
      },
      evidence_refs: [],
      expected_effect: ["future model option patch"],
      risks: ["semantic validation remains model-owned"],
      created_at: "2026-07-18T00:00:00Z",
      fingerprint: "fp-model-options",
      status: "pending",
    }];

    render(
      <AgentSurfaceContext.Provider value={withProposal}>
        <AgentPanel runId="run-a" projectRoot="/proj" />
      </AgentSurfaceContext.Provider>,
    );

    const card = screen.getByTestId("agent-proposal-proposal-model-options");
    expect(card).toHaveTextContent(
      'model_options: {"old":{"nested":true},"new":["a legitimate future option value"],"additional_option":true}',
    );
    expect(card).not.toHaveTextContent("→");
  });

  it("renders an NL data-cast proposal as readable intent, not raw JSON", () => {
    const withProposal = value();
    withProposal.proposals = [{
      record_type: "revision",
      proposal_id: "proposal-cast",
      operation_id: "data.columns.cast",
      operation_version: "v1",
      revision: 1,
      session_id: "session-1",
      chain_id: "chain-a",
      command_id: null,
      target: { run_id: "run-a", node_ref: "stage:cleaned" },
      preconditions: { active_head_run_id: "run-a" },
      changes: {
        casts: [
          { column: "wage", target_dtype: "string" },
          { column: "education", target_dtype: "string" },
        ],
        output_format: "csv",
      },
      evidence_refs: [],
      expected_effect: ["two columns become categorical labels"],
      risks: ["downstream model rerun required"],
      created_at: "2026-07-16T00:00:00Z",
      fingerprint: "fp-cast",
      status: "pending",
    }];
    render(
      <AgentSurfaceContext.Provider value={withProposal}>
        <AgentPanel runId="run-a" projectRoot="/proj" />
      </AgentSurfaceContext.Provider>,
    );

    const card = screen.getByTestId("agent-proposal-proposal-cast");
    expect(card).toHaveTextContent("Cast wage → string, education → string");
    // The array must not leak through as JSON.
    expect(card.textContent).not.toContain("target_dtype");
    expect(card.textContent).not.toContain("[{");
  });

  it("does not duplicate project navigation links already available in AI activity", () => {
    const navigationLinks: AgentNavigationRef[] = [{
      kind: "run",
      id: "run-child",
      label: "Child run run-child",
      relation: "child",
      available: true,
      href: { view: "graph", run_id: "run-child" },
    }];
    render(
      <AgentSurfaceContext.Provider
        value={value({ navigationLinks, openNavigation: vi.fn() })}
      >
        <AgentPanel runId="run-a" projectRoot="/proj" />
      </AgentSurfaceContext.Provider>,
    );

    expect(screen.queryByTestId("agent-navigation-links")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /open child run/i })).not.toBeInTheDocument();
  });

  it("offers a human-readable audit export for the operation's owning session", () => {
    const navigationLinks: AgentNavigationRef[] = [{
      kind: "operation",
      id: "oprec-1",
      label: "model.rerun · completed",
      relation: "audit",
      available: true,
      href: {
        view: "agent",
        session_id: "agent_chain",
        operation_record_id: "oprec-1",
      },
    }];
    render(
      <AgentSurfaceContext.Provider value={value({ navigationLinks })}>
        <AgentPanel runId="run-a" projectRoot="/proj" />
      </AgentSurfaceContext.Provider>,
    );

    const link = screen.getByRole("link", { name: "Export Agent audit" });
    expect(link).toHaveAttribute(
      "href",
      expect.stringContaining("/agent/sessions/agent_chain/audit?project_root=%2Fproj&format=html"),
    );
  });

  it("keeps message navigation keys unique when one chain has two relations", () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    const duplicateChainId = "chain-message";
    const withMessageLinks = value({
      navigationLinks: [],
      messages: [{
        entry_id: "message-chain-links",
        role: "assistant",
        content: "已定位到链路。",
        stop_reason: "stop",
        navigation: [
          {
            kind: "chain",
            id: duplicateChainId,
            label: `Chain ${duplicateChainId}`,
            relation: "parent",
            available: true,
            href: { view: "agent", chain_id: duplicateChainId },
          },
          {
            kind: "chain",
            id: duplicateChainId,
            label: `Chain ${duplicateChainId}`,
            relation: "child",
            available: true,
            href: { view: "agent", chain_id: duplicateChainId },
          },
        ],
      }],
    });

    render(
      <AgentSurfaceContext.Provider value={withMessageLinks}>
        <AgentPanel runId="run-a" projectRoot="/proj" />
      </AgentSurfaceContext.Provider>,
    );

    expect(screen.getByRole("button", { name: "Open parent Chain chain-message" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open child Chain chain-message" })).toBeInTheDocument();
    expect(consoleError.mock.calls.flat().join(" ")).not.toContain("same key");
    consoleError.mockRestore();
  });

  it("renders message-level navigation refs as secondary terminal links", () => {
    const openNavigation = vi.fn();
    const withMessageLink = value({ openNavigation });
    withMessageLink.navigationLinks = [];
    withMessageLink.messages = [{
      entry_id: "a1",
      role: "assistant",
      content: "已核对源模型。",
      navigation: [{
        kind: "graph_node",
        id: "run-source::model:ols_1",
        label: "Source model:ols_1",
        relation: "source",
        available: true,
        href: {
          view: "graph",
          run_id: "run-source",
          node_ref: "model:ols_1",
          forest_node_key: "run-source::model:ols_1",
        },
      }],
    }];

    render(
      <AgentSurfaceContext.Provider value={withMessageLink}>
        <AgentPanel runId="run-a" projectRoot="/proj" />
      </AgentSurfaceContext.Provider>,
    );

    const link = screen.getByRole("button", { name: /open source model/i });
    expect(link).toBeInTheDocument();
    expect(link).toHaveClass("wb-agent-message-link");
    fireEvent.click(link);
    expect(openNavigation).toHaveBeenCalledWith(
      expect.objectContaining({ kind: "graph_node", id: "run-source::model:ols_1" }),
    );
  });

  it("offers decline and bounded revision actions for a pending proposal", async () => {
    const declineProposal = vi.fn().mockResolvedValue(true);
    const reviseProposal = vi.fn().mockResolvedValue(true);
    const withProposal = value({ declineProposal, reviseProposal });
    withProposal.proposals = [{
      record_type: "revision",
      proposal_id: "proposal-1",
      operation_id: "model.rerun",
      operation_version: "v1",
      revision: 1,
      session_id: "session-1",
      chain_id: "chain-a",
      command_id: null,
      target: { run_id: "run-a", node_ref: "model:ols_1" },
      preconditions: { active_head_run_id: "run-a" },
      changes: { covariance: { old: "nonrobust", new: "HC1" } },
      evidence_refs: [],
      expected_effect: ["standard errors may change"],
      risks: ["small samples"],
      created_at: "2026-07-14T00:00:00Z",
      fingerprint: "fingerprint-1",
      status: "pending",
    }];
    render(
      <AgentSurfaceContext.Provider value={withProposal}>
        <AgentPanel runId="run-a" projectRoot="/proj" />
      </AgentSurfaceContext.Provider>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Decline proposal proposal-1" }));
    expect(declineProposal).toHaveBeenCalledWith("proposal-1");

    fireEvent.click(screen.getByRole("button", { name: "Revise proposal proposal-1" }));
    const editor = screen.getByRole("textbox", { name: "Proposal changes proposal-1" });
    fireEvent.change(editor, {
      target: { value: '{"covariance":{"old":"nonrobust","new":"unadjusted"}}' },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save revision proposal-1" }));
    expect(reviseProposal).toHaveBeenCalledWith(
      "proposal-1",
      1,
      { covariance: { old: "nonrobust", new: "unadjusted" } },
    );
  });

  it("provides the single terminal composer inside the Agent panel", () => {
    const withPrompt = value({ prompt: "inspect the active head" });
    render(
      <AgentSurfaceContext.Provider value={withPrompt}>
        <AgentPanel runId="run-a" projectRoot="/proj" />
      </AgentSurfaceContext.Provider>,
    );

    // The Agent panel owns the single terminal-like input. There must not be
    // be a second graph composer for the same prompt state.
    expect(screen.getByRole("textbox", { name: "Ask Agent" })).toBeInTheDocument();
    expect(screen.getByRole("listbox", { name: "Agent model" })).toBeInTheDocument();
    expect(screen.getByTestId("agent-context-ring")).toBeInTheDocument();
    expect(screen.getByTestId("agent-terminal-prompt-marker")).toHaveTextContent("❯");
    expect(screen.queryByRole("textbox", { name: "Agent terminal input" })).not.toBeInTheDocument();
    expect(screen.queryByTestId("agent-terminal-input-row")).not.toBeInTheDocument();
    expect(screen.queryByTestId("agent-terminal-input-moved-hint")).not.toBeInTheDocument();
  });

  it("renders assistant Markdown as readable terminal blocks", () => {
    const withMarkdown = value();
    withMarkdown.messages = [
      { entry_id: "a-md", role: "assistant", content: "## Findings\n\n**Stable** result", stop_reason: "stop" },
    ];
    render(
      <AgentSurfaceContext.Provider value={withMarkdown}>
        <AgentPanel runId="run-a" projectRoot="/proj" />
      </AgentSurfaceContext.Provider>,
    );

    expect(screen.getByRole("heading", { name: "Findings" })).toBeInTheDocument();
    expect(screen.getByText("Stable")).toBeInTheDocument();
    expect(screen.queryByText("## Findings")).not.toBeInTheDocument();
    expect(screen.queryByText("**Stable** result")).not.toBeInTheDocument();
  });
});
