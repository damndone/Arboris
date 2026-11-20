import "@testing-library/jest-dom/vitest";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import { AgentPanel, toolStatusLine } from "./AgentPanel";
import {
  AgentSurfaceContext,
  type AgentSurfaceContextValue,
} from "./AgentSurfaceContext";
import type { AgentHierarchyNode, AgentNavigationRef } from "./agentTypes";
import { agentMessageFixture, agentProposalFixture, llmModelFixture } from "../../apiFixtures";

function value(overrides: Partial<AgentSurfaceContextValue> = {}): AgentSurfaceContextValue {
  return {
    messages: [
      agentMessageFixture({ entry_id: "u1", role: "user", content: "检查 active head", stop_reason: null }),
      agentMessageFixture({ entry_id: "a1", role: "assistant", content: "发现一个待确认的风险。", stop_reason: "stop" }),
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
    modelOptions: [llmModelFixture({ display_name: "DeepSeek V4 Flash", request_model: "deepseek-v4-flash", context_window_tokens: 32_000, supports_1m: false })],
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

// Public leverage replay, session projection SHA256 de0cd02b0bc64e4f8dd3fbb541be100d1c746ebcb1cd889a7d4c5ee4c7fe3388.
const recordedToolNavigation: AgentNavigationRef[] = [
  {
    "kind": "proposal",
    "id": "proposal_2006a1c0fcfe4b7ab4f874b8769b08d7",
    "label": "Proposal proposal_2006a1c0fcfe4b7ab4f874b8769b08d7",
    "relation": "audit",
    "available": true,
    "href": {
      "view": "agent",
      "session_id": "agent_chain_a4dc89f57c224a2cbdfb01add1941870",
      "proposal_id": "proposal_2006a1c0fcfe4b7ab4f874b8769b08d7"
    }
  },
  {
    "kind": "graph_node",
    "id": "216323ff831a20e1a096ee3060b4e137fa8b6f88999e691de995a98538c338ef::model:ols_1",
    "label": "Source model:ols_1",
    "relation": "source",
    "available": true,
    "href": {
      "view": "graph",
      "run_id": "20261029_040736_004116_47b20a4f",
      "node_ref": "model:ols_1",
      "forest_node_key": "216323ff831a20e1a096ee3060b4e137fa8b6f88999e691de995a98538c338ef::model:ols_1",
      "node_hash": "216323ff831a20e1a096ee3060b4e137fa8b6f88999e691de995a98538c338ef"
    }
  },
  {
    "kind": "run",
    "id": "20261029_040913_735959_317312a4",
    "label": "Child run 20261029_040913_735959_317312a4",
    "relation": "child",
    "available": true,
    "href": {
      "view": "graph",
      "run_id": "20261029_040913_735959_317312a4",
      "session_id": "session_chain_8c8cf6f0bc28e9982f56c71b3cb2c197"
    }
  },
  {
    "kind": "fork",
    "id": "fork_8c8cf6f0bc28e9982f56c71b3cb2c197",
    "label": "Fork fork_8c8cf6f0bc28e9982f56c71b3cb2c197",
    "relation": "child",
    "available": true,
    "href": {
      "view": "graph",
      "fork_id": "fork_8c8cf6f0bc28e9982f56c71b3cb2c197",
      "run_id": "20261029_040913_735959_317312a4"
    }
  },
  {
    "kind": "chain",
    "id": "chain_8c8cf6f0bc28e9982f56c71b3cb2c197",
    "label": "Chain chain_8c8cf6f0bc28e9982f56c71b3cb2c197",
    "relation": "child",
    "available": true,
    "href": {
      "view": "agent",
      "chain_id": "chain_8c8cf6f0bc28e9982f56c71b3cb2c197",
      "session_id": "session_chain_8c8cf6f0bc28e9982f56c71b3cb2c197"
    }
  },
  {
    "kind": "agent_session",
    "id": "session_chain_8c8cf6f0bc28e9982f56c71b3cb2c197",
    "label": "Agent session_chain_8c8cf6f0bc28e9982f56c71b3cb2c197",
    "relation": "child",
    "available": true,
    "href": {
      "view": "agent",
      "session_id": "session_chain_8c8cf6f0bc28e9982f56c71b3cb2c197"
    }
  },
  {
    "kind": "operation",
    "id": "oprec_0e2f4a619720bce2f6906dbf",
    "label": "model.rerun · completed",
    "relation": "audit",
    "available": true,
    "href": {
      "view": "agent",
      "session_id": "agent_chain_a4dc89f57c224a2cbdfb01add1941870",
      "operation_record_id": "oprec_0e2f4a619720bce2f6906dbf"
    }
  },
  {
    "kind": "diff",
    "id": "oprec_0e2f4a619720bce2f6906dbf",
    "label": "Diff · input_diff.v1",
    "relation": "result",
    "available": true,
    "href": {
      "view": "agent",
      "session_id": "agent_chain_a4dc89f57c224a2cbdfb01add1941870",
      "operation_record_id": "oprec_0e2f4a619720bce2f6906dbf",
      "diff": "1"
    }
  }
];

describe("toolStatusLine — public failure summaries", () => {
  it("shows the first usable public tool error message with a bounded length", () => {
    const line = toolStatusLine(JSON.stringify({ ok: false, error: "ToolVisibleError", error_details: [
      { message: " " }, { message: `The requested result artifact is unavailable.\n${"x".repeat(500)}` }, { message: "SECOND_DETAIL" },
    ] }), "inspect_model_result");
    expect(line).toContain("inspect_model_result ✗ ToolVisibleError");
    expect(line).toContain("The requested result artifact is unavailable.");
    expect(line).not.toContain("SECOND_DETAIL");
    expect(line).not.toContain("\n");
    expect(line.length).toBeLessThanOrEqual(300);
  });

  it("reports a rejected plan save and its inner error even when the envelope is ok", () => {
    const line = toolStatusLine(JSON.stringify({ ok: true, output: { saved: false, error: "Approval criteria cannot be changed after execution." } }), "update_plan");
    expect(line).toContain("✗ not saved");
    expect(line).toContain("Approval criteria cannot be changed after execution.");
    expect(line).not.toContain("✓");
  });

  it("reports unavailable declared public result views without claiming success", () => {
    for (const output of [
      { available: false, reason: "ARMA_GARCH_PUBLIC_ARTIFACTS_UNAVAILABLE" },
      { time_series_summary: { available: false, reason_code: "TIME_SERIES_MODEL_IDENTITY_CONFLICT" } },
      { artifact_evidence: { available: false, reason: "This artifact type has no registered public Agent result view. Read model estimates with inspect_project_model_coefficients using run_ids [\"run-source\"]." } },
    ]) {
      const line = toolStatusLine(JSON.stringify({ ok: true, output }), "artifact_evidence" in output ? "inspect_operation_artifact" : "inspect_model_result");
      expect(line).toContain("✗ result unavailable");
      expect(line).toMatch(/ARMA_GARCH_PUBLIC_ARTIFACTS_UNAVAILABLE|TIME_SERIES_MODEL_IDENTITY_CONFLICT|inspect_project_model_coefficients using run_ids \["run-source"\]/);
      expect(line).not.toContain("✓");
    }
  });
});

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
          p_value: 9.1e-74,
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
    expect(results).toHaveTextContent("p value: < 0.001");
    expect(results).not.toHaveTextContent("p value: 0.0000");
    // The out-of-range flag is what separates a number from a claim.
    expect(results).toHaveTextContent("stationary point within observed range: no");
    expect(results).not.toHaveTextContent("workbench.model.quadratic");
  });

  it("shows a nested evidence packet as readable lines, never as raw JSON", () => {
    const evidence = {
      ...workflowOperation.postEstimationResults[0],
      artifact_id: "workflow_test_evidence",
      operation_id: "test.evidence",
      workflow_step_id: "paired",
      result: {
        family: "evidence",
        result: {
        payload_schema: "workbench.statistics.evidence-packet",
        producer: { component: "workbench.statistical_tests" },
        dataset_ref: { dataset_sha256: null },
        correction_scope: "advanced_evidence_family",
        results: [{
          test_id: "paired_t_test:a:b",
          test_type: "paired_t_test",
          nobs: 197,
          statistic: 2.05588,
          p_value: 0.04126,
          p_value_corrected: 0.0825,
          effect_size: { effect_size_name: "mean_paired_difference", value: 4.0863 },
          warnings: [],
          source_id: "statistical_tests.evidence.paired_t_test.a.b",
        }],
        },
      },
    };
    render(
      <AgentSurfaceContext.Provider value={value({ activeOperation: { ...workflowOperation, postEstimationResults: [evidence] } })}>
        <AgentPanel runId="run-a" projectRoot="/proj" />
      </AgentSurfaceContext.Provider>,
    );

    const results = screen.getByTestId("agent-operation-post-estimation");
    expect(results).toHaveTextContent("test type: paired_t_test · nobs: 197 · statistic: 2.0559 · p value: 0.041");
    expect(results).toHaveTextContent("effect size: mean_paired_difference 4.0863");
    expect(results).not.toHaveTextContent("{");
    expect(results).not.toHaveTextContent("workbench.statistics");
    expect(results).not.toHaveTextContent("paired_t_test:a:b");
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
  it.each([
    ["tool_execution_start", "Waiting for the model"],
    ["tool_execution_end", "Waiting for the model"],
    ["message_update", "Writing"],
  ])("distinguishes observable activity for %s", (lastEventType, expected) => {
    render(<AgentSurfaceContext.Provider value={value({ sessionStatus: "running", lastEventType })}>
      <AgentPanel runId="run-a" projectRoot="/proj" />
    </AgentSurfaceContext.Provider>);
    expect(screen.getByTestId("agent-execution-trace")).toHaveTextContent(expected);
  });

  it("follows a growing public tool activity only while the reader stays at the transcript bottom", () => {
    const first = { session_id: "saved", command_id: "command", tool_call_id: "first", tool_id: "inspect_node_context" };
    const second = { ...first, tool_call_id: "second", tool_id: "inspect_data_schema" };
    const context = value({ sessionStatus: "running", activeToolCalls: [first] });
    const view = render(<AgentSurfaceContext.Provider value={context}><AgentPanel runId="run-a" projectRoot="/proj" /></AgentSurfaceContext.Provider>);
    const transcript = screen.getByRole("log", { name: /Agent transcript/ });
    Object.defineProperties(transcript, { clientHeight: { configurable: true, value: 100 }, scrollHeight: { configurable: true, value: 500 } });
    transcript.scrollTop = 400;
    fireEvent.scroll(transcript);
    Object.defineProperty(transcript, "scrollHeight", { configurable: true, value: 620 });
    view.rerender(<AgentSurfaceContext.Provider value={{ ...context, activeToolCalls: [first, second] }}><AgentPanel runId="run-a" projectRoot="/proj" /></AgentSurfaceContext.Provider>);
    expect(transcript.scrollTop).toBe(620);

    transcript.scrollTop = 180;
    fireEvent.scroll(transcript);
    Object.defineProperty(transcript, "scrollHeight", { configurable: true, value: 740 });
    view.rerender(<AgentSurfaceContext.Provider value={{ ...context, activeToolCalls: [second] }}><AgentPanel runId="run-a" projectRoot="/proj" /></AgentSurfaceContext.Provider>);
    expect(transcript.scrollTop).toBe(180);
  });

  it("retains an entire long public tool label in the working row", () => {
    const toolId = `inspect_${"longlabel".repeat(16)}`;
    render(<AgentSurfaceContext.Provider value={value({ sessionStatus: "running", lastEventType: "tool_execution_start",
      activeToolCalls: [{ session_id: "saved", command_id: "command", tool_call_id: "long", tool_id: toolId }],
    })}>
      <AgentPanel runId="run-a" projectRoot="/proj" />
    </AgentSurfaceContext.Provider>);
    expect(screen.getByTestId("agent-execution-trace")).toHaveTextContent(toolId.replace("inspect_", "").replace(/_/g, " "));
  });

  it("shows a prepared plan proposal as waiting for the Agent to link it", () => {
    render(<AgentSurfaceContext.Provider value={value({ messages: [
      agentMessageFixture({ entry_id: "u1", role: "user", content: "Plan an IV estimate." }),
      agentMessageFixture({
        entry_id: "t1", role: "tool", name: "run_operation",
        activity: { target: "Estimate iv_2sls", seconds: null },
        content: JSON.stringify({ ok: true, output: {
          prepared: true,
          proposal_ref: { proposal_id: "prepared-iv", revision: 1, fingerprint: "fingerprint" },
          operation_ids: ["model.genesis"],
          guidance: "Bind proposal_ref to a plan step with update_plan. This request has not executed.",
        } }),
      }),
    ] })}><AgentPanel runId="run-a" projectRoot="/proj" /></AgentSurfaceContext.Provider>);

    const receipt = screen.getByTestId("agent-message-tool");
    expect(receipt).toHaveTextContent("Prepared a proposal for Estimate iv_2sls");
    expect(receipt).toHaveTextContent("Waiting for the Agent to link it to a plan step");
    expect(receipt).not.toHaveTextContent(/✓|Ran|Waiting for your confirmation/);
    expect(screen.queryByRole("button", { name: /Confirm proposal/ })).not.toBeInTheDocument();
  });

  it("keeps a previous turn's terminal failure visible after a follow-up is recorded", () => {
    render(<AgentSurfaceContext.Provider value={value({ messages: [
      agentMessageFixture({ entry_id: "u1", role: "user", content: "First task" }),
      agentMessageFixture({ entry_id: "t1", role: "tool", content: '{"ok":true}' }),
      agentMessageFixture({ entry_id: "a1", role: "assistant", content: "Partial result", stop_reason: "stop" }),
      agentMessageFixture({ entry_id: "a2", role: "assistant", content: "Timed out", stop_reason: "error", error: "agent_timeout" }),
      agentMessageFixture({ entry_id: "u2", role: "user", content: "Continue" }),
    ] })}>
      <AgentPanel runId="run-a" projectRoot="/proj" />
    </AgentSurfaceContext.Provider>);
    expect(screen.getByTestId("agent-reasoning-u1")).toHaveTextContent("Stopped");
    expect(screen.getByTestId("agent-reasoning-u1")).not.toHaveTextContent("Worked ·");
  });

  it("says a turn was stopped when the stop left no reply", () => {
    render(<AgentSurfaceContext.Provider value={value({ messages: [
      agentMessageFixture({ entry_id: "u1", role: "user", content: "Task" }),
      agentMessageFixture({ entry_id: "a1", role: "assistant", content: "", stop_reason: "aborted" }),
    ] })}>
      <AgentPanel runId="run-a" projectRoot="/proj" />
    </AgentSurfaceContext.Provider>);
    expect(screen.getByTestId("agent-turn-stopped")).toHaveTextContent("Stopped");
  });

  it("does not invent zero elapsed time or a final-answer phase for external model requests", () => {
    render(<AgentSurfaceContext.Provider value={value({ sessionStatus: "running", lastEventType: "message_start" })}>
      <AgentPanel runId="run-a" projectRoot="/proj" />
    </AgentSurfaceContext.Provider>);
    expect(screen.getByTestId("agent-execution-trace")).toHaveTextContent("Waiting for the model");
    expect(screen.getByTestId("agent-execution-trace")).toHaveTextContent("Elapsed time unavailable");
    expect(screen.getByTestId("agent-turn-progress")).not.toHaveTextContent("0s");
  });

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
    expect(screen.getByTestId("agent-execution-trace")).toHaveTextContent("Waiting for the model");
  });

  it("shows an actionable provider failure without leaving the turn marked as working", () => {
    render(
      <AgentSurfaceContext.Provider value={value({
        sessionStatus: "failed",
        messages: [
          agentMessageFixture({ entry_id: "u1", role: "user", content: "Prepare a workflow", stop_reason: null }),
          agentMessageFixture({ entry_id: "a1", role: "assistant", content: "", stop_reason: "error", error: "LLMUpstreamError" }),
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
      "Completed operations and results remain recorded",
    );
  });

  it("guides an output-limited turn to its own receipts and exactly bound operation without continuing", () => {
    const openNavigation = vi.fn().mockReturnValue(true);
    const context = value({ sessionStatus: "failed", openNavigation, resumeTurn: vi.fn(), continueTurn: vi.fn(), messages: [
      agentMessageFixture({ entry_id: "old-user", role: "user", content: "Earlier work" }),
      agentMessageFixture({ entry_id: "old-tool", role: "tool", content: JSON.stringify({ ok: true, output: { operation: { record_id: "old-operation", status: "completed" } } }) }),
      agentMessageFixture({ entry_id: "old-answer", role: "assistant", content: "Earlier work recorded.", stop_reason: "stop" }),
      agentMessageFixture({ entry_id: "current-user", role: "user", content: "Finish this report" }),
      agentMessageFixture({ entry_id: "current-tool", role: "tool", name: "run_operation", content: JSON.stringify({ ok: true, output: { operation: { record_id: "current-operation", status: "completed" } } }), navigation: [
        { kind: "operation", id: "old-operation", label: "Earlier operation", relation: "audit", available: true, href: { view: "agent", operation_record_id: "old-operation" } },
        { kind: "operation", id: "current-operation", label: "Current recorded operation", relation: "audit", available: true, href: { view: "agent", operation_record_id: "current-operation" } },
      ] }),
      // Actual terminal metadata from the v3 IV recording (source SHA256 e7623e540ddf26f5825a1ee1695d2b5d128aa781e10f08d7bdb94119fda6c84a).
      agentMessageFixture({ entry_id: "6e5b49a69da34aa18da4010b86f21288", role: "assistant", content: "本次回复达到模型输出上限，没有写完，不能作为完整回答；其中的数字尚未核验。", stop_reason: "error", error: "provider_output_limit" }),
    ] });
    render(<AgentSurfaceContext.Provider value={context}><AgentPanel runId="run-a" projectRoot="/proj" /></AgentSurfaceContext.Provider>);
    const callout = screen.getByTestId("agent-turn-error");
    expect(callout).toHaveTextContent("The model reached its response limit before finishing");
    const current = screen.getByTestId("agent-reasoning-current-user");
    const old = screen.getByTestId("agent-reasoning-old-user");
    const scroll = vi.fn();
    Object.defineProperty(current, "scrollIntoView", { configurable: true, value: scroll });
    fireEvent.click(current.querySelector("summary")!);
    expect(current).not.toHaveAttribute("open");
    fireEvent.click(within(callout).getByRole("button", { name: "Review recorded steps" }));
    expect(current).toHaveAttribute("open");
    expect(current.querySelector("summary")).toHaveFocus();
    expect(scroll).toHaveBeenCalled();
    expect(old).not.toHaveAttribute("open");
    fireEvent.click(within(callout).getByRole("button", { name: "Open recorded operation" }));
    expect(openNavigation).toHaveBeenCalledWith(context.messages[4].navigation[1]);
    expect(screen.getByText("本次回复达到模型输出上限，没有写完，不能作为完整回答；其中的数字尚未核验。")).toBeVisible();
    expect(context.sendPrompt).not.toHaveBeenCalled();
    expect(context.resumeTurn).not.toHaveBeenCalled();
    expect(context.continueTurn).not.toHaveBeenCalled();
  });

  it("offers the stopped reply when this turn has no receipts instead of linking historical work", () => {
    const context = value({ sessionStatus: "failed", openNavigation: vi.fn(), messages: [
      agentMessageFixture({ entry_id: "old-user", role: "user", content: "Earlier work" }),
      agentMessageFixture({ entry_id: "old-tool", role: "tool", content: JSON.stringify({ ok: true, output: { operation: { record_id: "old-operation", status: "completed" } } }), navigation: [
        { kind: "operation", id: "old-operation", label: "Earlier operation", relation: "audit", available: true, href: { view: "agent", operation_record_id: "old-operation" } },
      ] }),
      agentMessageFixture({ entry_id: "old-answer", role: "assistant", content: "Earlier work recorded.", stop_reason: "stop" }),
      agentMessageFixture({ entry_id: "current-user", role: "user", content: "A new task" }),
      agentMessageFixture({ entry_id: "current-error", role: "assistant", content: "The request timed out before a result was recorded.", stop_reason: "error", error: "agent_timeout" }),
    ] });
    render(<AgentSurfaceContext.Provider value={context}><AgentPanel runId="run-a" projectRoot="/proj" /></AgentSurfaceContext.Provider>);
    const callout = screen.getByTestId("agent-turn-error");
    expect(callout).toHaveTextContent("The time limit was reached before the request finished");
    expect(callout).toHaveTextContent("No tool receipts are recorded in this turn");
    expect(within(callout).queryByRole("button", { name: "Review recorded steps" })).not.toBeInTheDocument();
    expect(within(callout).queryByRole("button", { name: "Open recorded operation" })).not.toBeInTheDocument();
    const reply = document.querySelector<HTMLElement>('[data-entry-id="current-error"]')!;
    const scroll = vi.fn();
    Object.defineProperty(reply, "scrollIntoView", { configurable: true, value: scroll });
    fireEvent.click(within(callout).getByRole("button", { name: "Review stopped reply" }));
    expect(reply).toHaveFocus();
    expect(scroll).toHaveBeenCalled();
    expect(context.openNavigation).not.toHaveBeenCalled();
    expect(context.sendPrompt).not.toHaveBeenCalled();
  });

  it("keeps unreadable stopped-turn receipts explicit and offers no unbound operation", () => {
    render(<AgentSurfaceContext.Provider value={value({ sessionStatus: "failed", openNavigation: vi.fn(), messages: [
      agentMessageFixture({ entry_id: "user", role: "user", content: "Finish the analysis" }),
      agentMessageFixture({ entry_id: "broken-tool", role: "tool", name: "inspect_model_result", content: "Unreadable receipt body", navigation: [
        { kind: "operation", id: "old-operation", label: "Unbound operation", relation: "audit", available: true, href: { view: "agent", operation_record_id: "old-operation" } },
      ] }),
      agentMessageFixture({ entry_id: "error", role: "assistant", content: "Stopped with work unfinished.", stop_reason: "error", error: "analysis_recovery_limit" }),
    ] })}><AgentPanel runId="run-a" projectRoot="/proj" /></AgentSurfaceContext.Provider>);
    const callout = screen.getByTestId("agent-turn-error");
    expect(callout).toHaveTextContent("Some receipt details could not be read");
    expect(screen.getByTestId("agent-message-tool")).toHaveTextContent("Unreadable receipt body");
    expect(within(callout).getByRole("button", { name: "Review recorded steps" })).toBeEnabled();
    expect(within(callout).queryByRole("button", { name: "Open recorded operation" })).not.toBeInTheDocument();
  });

  it("does not offer an unavailable recorded operation as a recovery result", () => {
    render(<AgentSurfaceContext.Provider value={value({ sessionStatus: "failed", openNavigation: vi.fn(), messages: [
      agentMessageFixture({ entry_id: "user", role: "user", content: "Finish the analysis" }),
      agentMessageFixture({ entry_id: "tool", role: "tool", name: "run_operation", content: JSON.stringify({ ok: true, output: { operation: { record_id: "missing-operation", status: "completed" } } }), navigation: [
        { kind: "operation", id: "missing-operation", label: "Missing operation", relation: "audit", available: false, reason: "The operation record is unavailable", href: { view: "agent", operation_record_id: "missing-operation" } },
      ] }),
      agentMessageFixture({ entry_id: "error", role: "assistant", content: "Stopped.", stop_reason: "error", error: "agent_timeout" }),
    ] })}><AgentPanel runId="run-a" projectRoot="/proj" /></AgentSurfaceContext.Provider>);
    expect(within(screen.getByTestId("agent-turn-error")).getByRole("button", { name: "Review recorded steps" })).toBeEnabled();
    expect(within(screen.getByTestId("agent-turn-error")).queryByRole("button", { name: "Open recorded operation" })).not.toBeInTheDocument();
  });

  it("does not link an operation when the navigation target disagrees with this turn's receipt", () => {
    render(<AgentSurfaceContext.Provider value={value({ sessionStatus: "failed", openNavigation: vi.fn(), messages: [
      agentMessageFixture({ entry_id: "user", role: "user", content: "Finish the analysis" }),
      agentMessageFixture({ entry_id: "tool", role: "tool", content: JSON.stringify({ ok: true, output: { operation: { record_id: "current-operation" } } }), navigation: [
        { kind: "operation", id: "current-operation", label: "Mismatched operation", relation: "audit", available: true, href: { view: "agent", operation_record_id: "old-operation" } },
      ] }),
      agentMessageFixture({ entry_id: "error", role: "assistant", content: "Stopped.", stop_reason: "error", error: "agent_timeout" }),
    ] })}><AgentPanel runId="run-a" projectRoot="/proj" /></AgentSurfaceContext.Provider>);
    const callout = screen.getByTestId("agent-turn-error");
    expect(within(callout).getByRole("button", { name: "Review recorded steps" })).toBeEnabled();
    expect(within(callout).queryByRole("button", { name: "Open recorded operation" })).not.toBeInTheDocument();
  });

  it("keeps a failed viewing action visible without starting recovery or analysis", () => {
    const context = value({ sessionStatus: "failed", openNavigation: vi.fn().mockReturnValue(false), resumeTurn: vi.fn(), continueTurn: vi.fn(), messages: [
      agentMessageFixture({ entry_id: "user", role: "user", content: "Finish the analysis" }),
      agentMessageFixture({ entry_id: "tool", role: "tool", content: JSON.stringify({ ok: true, output: { operation: { record_id: "current-operation" } } }), navigation: [
        { kind: "operation", id: "current-operation", label: "Recorded operation", relation: "audit", available: true, href: { view: "agent", operation_record_id: "current-operation" } },
      ] }),
      agentMessageFixture({ entry_id: "error", role: "assistant", content: "Stopped.", stop_reason: "error", error: "agent_timeout" }),
    ] });
    render(<AgentSurfaceContext.Provider value={context}><AgentPanel runId="run-a" projectRoot="/proj" /></AgentSurfaceContext.Provider>);
    const callout = screen.getByTestId("agent-turn-error");
    fireEvent.click(within(callout).getByRole("button", { name: "Open recorded operation" }));
    expect(within(callout).getByRole("alert")).toHaveTextContent("The recorded operation could not be opened");
    expect(context.sendPrompt).not.toHaveBeenCalled();
    expect(context.resumeTurn).not.toHaveBeenCalled();
    expect(context.continueTurn).not.toHaveBeenCalled();
  });

  it.each(["agent_timeout", "tool_runtime_error"])("retains completed work when reporting %s", error => {
    render(<AgentSurfaceContext.Provider value={value({messages: [
      agentMessageFixture({entry_id: "u1", role: "user", content: "Fit the model."}),
      agentMessageFixture({entry_id: "t1", role: "tool", name: "run_operation",
        content: JSON.stringify({ok: true, output: {executed: true}})}),
      agentMessageFixture({entry_id: "a1", role: "assistant", content: "", stop_reason: "error", error}),
    ]})}><AgentPanel runId="run-a" projectRoot="/proj" /></AgentSurfaceContext.Provider>);
    expect(screen.getByTestId("agent-turn-error")).toHaveTextContent("Completed operations and results remain recorded");
    expect(screen.getByTestId("agent-turn-error")).not.toHaveTextContent(/nothing.*was changed/i);
    expect(screen.getByTestId("agent-reasoning-u1")).toHaveTextContent("Ran an operation");
  });

  it("explains a budget yield without claiming another request timed out or automatically continuing", () => {
    const context = value({ sessionStatus: "blocked", continueTurn: vi.fn(), resumeTurn: vi.fn(), messages: [
      agentMessageFixture({ entry_id: "u1", role: "user", content: "Inspect the saved analysis." }),
      agentMessageFixture({ entry_id: "t1", role: "tool", name: "inspect_result_summary",
        content: JSON.stringify({ ok: true, output: { summary: "The saved model is available." } }) }),
      agentMessageFixture({ entry_id: "a1", role: "assistant", content: "Earlier results are saved.",
        stop_reason: "error", error: "provider_request_budget" }),
    ] });
    render(<AgentSurfaceContext.Provider value={context}><AgentPanel runId="run-a" projectRoot="/proj" /></AgentSurfaceContext.Provider>);
    const callout = screen.getByTestId("agent-turn-error");
    expect(callout).toHaveTextContent("The next model request was not sent");
    expect(callout).toHaveTextContent("Completed operations and results remain recorded");
    expect(callout).not.toHaveTextContent(/timed out|time limit was reached|analysis complete/i);
    expect(context.sendPrompt).not.toHaveBeenCalled();
    expect(context.continueTurn).not.toHaveBeenCalled();
    expect(context.resumeTurn).not.toHaveBeenCalled();
  });

  it.each(["running", "working", "cancelling"])("does not describe an unconfirmed stop as terminal while the restored turn is %s", (sessionStatus) => {
    const error = "Could not confirm a stop. The server may still be running. Retry Stop.";
    render(<AgentSurfaceContext.Provider value={value({ isSubmitting: false, sessionStatus, error })}>
      <AgentPanel runId="run-a" projectRoot="/proj" />
    </AgentSurfaceContext.Provider>);
    expect(screen.queryByTestId("agent-turn-error")).not.toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(error);
    expect(screen.queryByText(/The Agent stopped before completing/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Stop Agent" })).toBeInTheDocument();
  });

  it("clears the failure once a later turn in the session answers", () => {
    render(
      <AgentSurfaceContext.Provider value={value({
        sessionStatus: "completed",
        messages: [
          agentMessageFixture({ entry_id: "u1", role: "user", content: "Is the gap significant?", stop_reason: null }),
          agentMessageFixture({ entry_id: "a1", role: "assistant", content: "", stop_reason: "error", error: "LLMUpstreamError:upstream_503" }),
          agentMessageFixture({ entry_id: "u2", role: "user", content: "Try again", stop_reason: null }),
          agentMessageFixture({ entry_id: "a2", role: "assistant", content: "Yes, t = 8.03, p < 0.001.", stop_reason: "stop" }),
        ],
      })}>
        <AgentPanel runId="run-a" projectRoot="/proj" />
      </AgentSurfaceContext.Provider>,
    );

    expect(screen.queryByTestId("agent-turn-error")).toBeNull();
  });

  it("reads a provider failure that carries its upstream status as a provider failure", () => {
    render(
      <AgentSurfaceContext.Provider value={value({
        sessionStatus: "failed",
        messages: [
          agentMessageFixture({ entry_id: "u1", role: "user", content: "Is the gap significant?", stop_reason: null }),
          agentMessageFixture({ entry_id: "a1", role: "assistant", content: "", stop_reason: "error", error: "LLMUpstreamError:upstream_503" }),
        ],
      })}>
        <AgentPanel runId="run-a" projectRoot="/proj" />
      </AgentSurfaceContext.Provider>,
    );

    expect(screen.getByTestId("agent-turn-error")).toHaveTextContent(
      "The configured provider did not return a usable response",
    );
  });

  it("distinguishes a terminal tool failure from an upstream provider failure", () => {
    render(
      <AgentSurfaceContext.Provider value={value({
        sessionStatus: "failed",
        messages: [
          agentMessageFixture({ entry_id: "u1", role: "user", content: "Inspect the model", stop_reason: null }),
          agentMessageFixture({ entry_id: "a1", role: "assistant", content: "", stop_reason: "error", error: "tool_runtime_error" }),
        ],
      })}>
        <AgentPanel runId="run-a" projectRoot="/proj" />
      </AgentSurfaceContext.Provider>,
    );

    const failure = screen.getByTestId("agent-turn-error");
    expect(failure).toHaveTextContent("tool runtime stopped unexpectedly");
    expect(failure).not.toHaveTextContent("configured provider");
  });

  it("shows a current approval failure ahead of an older turn error", () => {
    render(<AgentSurfaceContext.Provider value={value({
      error: "This proposal has already been decided. Reload the proposal.",
      messages: [agentMessageFixture({ entry_id: "old", role: "assistant", content: "", stop_reason: "error", error: "max_steps_exceeded" })],
    })}>
      <AgentPanel runId="run-a" projectRoot="/proj" />
    </AgentSurfaceContext.Provider>);
    expect(screen.getByTestId("agent-turn-error")).toHaveTextContent("This proposal has already been decided.");
  });

  it("keeps a historical step-budget stop accurate when a proposal is pending", () => {
    render(
      <AgentSurfaceContext.Provider value={value({
        sessionStatus: "blocked",
        messages: [
          agentMessageFixture({ entry_id: "u1", role: "user", content: "Prepare a workflow", stop_reason: null }),
          agentMessageFixture({ entry_id: "a1", role: "assistant", content: "", stop_reason: "error", error: "max_steps_exceeded" }),
        ],
        proposals: [agentProposalFixture({
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
        })],
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
      "Completed operations and results remain recorded",
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
      messages: [agentMessageFixture({ entry_id: "u1", role: "user", content: "检查结果", stop_reason: null })],
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
          agentMessageFixture({ entry_id: "a1", role: "assistant", content: "这是最新输出。", stop_reason: "stop" }),
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
          agentMessageFixture({ entry_id: "a1", role: "assistant", content: "这是最新输出。\n\n补充说明。", stop_reason: "stop" }),
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
        agentMessageFixture({ entry_id: "u1", role: "user", content: "检查模型结果", stop_reason: null }),
        agentMessageFixture({
          entry_id: "a1",
          role: "assistant",
          content: "我会先核对模型和诊断证据。",
          stop_reason: "tool_calls",
        }),
        agentMessageFixture({
          entry_id: "t1",
          role: "tool",
          name: "inspect_model_result",
          content: JSON.stringify({ ok: true, output: { result_id: "result-1" } }),
          stop_reason: null,
        }),
        agentMessageFixture({
          entry_id: "a2",
          role: "assistant",
          content: "模型结果已核对：系数为正。",
          stop_reason: "stop",
        }),
      ],
    });

    render(
      <AgentSurfaceContext.Provider value={withReasoning}>
        <AgentPanel runId="run-a" projectRoot="/proj" />
      </AgentSurfaceContext.Provider>,
    );

    const reasoning = screen.getByTestId("agent-reasoning-u1");
    expect(reasoning).toHaveTextContent("2 steps");
    expect(reasoning).toHaveTextContent("我会先核对模型和诊断证据。");
    expect(reasoning).toHaveTextContent("Read model result");
    expect(reasoning).not.toContainElement(screen.getByText("模型结果已核对：系数为正。"));
  });

  it.each(["running", "interrupted", "completed"])("keeps the latest recorded actions visible while %s and retains an older error summary", sessionStatus => {
    const openNavigation = vi.fn();
    const resultLink: AgentNavigationRef = {
      kind: "graph_node", id: "result-1", label: "Result model", relation: "result", available: true,
      href: { view: "graph", run_id: "run-child", node_ref: "model:ols_1" },
    };
    render(<AgentSurfaceContext.Provider value={value({
      sessionStatus, openNavigation,
      messages: [
        agentMessageFixture({ entry_id: "u0", role: "user", content: "Earlier task" }),
        agentMessageFixture({ entry_id: "t0", role: "tool", name: "inspect_data", content: JSON.stringify({ ok: false, error: "missing_column" }) }),
        agentMessageFixture({ entry_id: "a0", role: "assistant", content: "Earlier task stopped.", stop_reason: "stop" }),
        agentMessageFixture({ entry_id: "u1", role: "user", content: "Current task" }),
        agentMessageFixture({ entry_id: "t1", role: "tool", name: "calculate", content: JSON.stringify({ ok: true, output: { results: [{ label: "Difference", expression: "8 - 3", value: "5" }], raw: "LARGE_RAW_OUTPUT" } }), navigation: [resultLink] }),
        agentMessageFixture({ entry_id: "t2", role: "tool", name: "inspect_result", content: JSON.stringify({ ok: false, error: "artifact_unavailable" }) }),
        ...(sessionStatus === "completed" ? [agentMessageFixture({ entry_id: "a1", role: "assistant", content: "Difference is 5; the artifact was unavailable.", stop_reason: "stop" })] : []),
      ],
    })}><AgentPanel projectRoot="/proj" runId="run-a" compactHeader /></AgentSurfaceContext.Provider>);

    const latest = screen.getByTestId("agent-reasoning-u1");
    expect(latest).toHaveAttribute("open");
    expect(latest).toHaveTextContent("Calculated — Difference: 8 - 3 = 5");
    expect(latest).toHaveTextContent("Read result — artifact_unavailable");
    expect(latest.querySelector("summary")).toHaveTextContent(sessionStatus === "running" ? "Working" : "Worked");
    expect(latest).not.toHaveTextContent("LARGE_RAW_OUTPUT");
    const previous = screen.getByTestId("agent-reasoning-u0");
    expect(previous).not.toHaveAttribute("open");
    expect(previous.querySelector("summary")).toHaveTextContent(/1 step/);
    fireEvent.click(screen.getByRole("button", { name: "Open result model" }));
    expect(openNavigation).toHaveBeenCalledWith(resultLink);
    expect(screen.queryByText(/recent steps/)).not.toBeInTheDocument();
  });

  it("keeps the last actual execution open after a follow-up has no recorded tools", () => {
    render(<AgentSurfaceContext.Provider value={value({sessionStatus: "interrupted", messages: [
      agentMessageFixture({entry_id: "u1", role: "user", content: "Fit the model."}),
      agentMessageFixture({entry_id: "t1", role: "tool", name: "inspect_result_summary",
        content: JSON.stringify({ok: true, output: {}})}),
      agentMessageFixture({entry_id: "a1", role: "assistant", content: "The fit is saved; diagnostics remain.", stop_reason: "stop"}),
      agentMessageFixture({entry_id: "u2", role: "user", content: "Continue."}),
    ]})}><AgentPanel runId="run-a" projectRoot="/proj" /></AgentSurfaceContext.Provider>);
    expect(screen.getByTestId("agent-reasoning-u1")).toHaveAttribute("open");
    expect(screen.getByText("Continue.")).toBeVisible();
  });

  it("files a draft withdrawn by the numeric check under reasoning and says why", () => {
    const withDraft = value({
      messages: [
        agentMessageFixture({ entry_id: "u1", role: "user", content: "男女工资有差别吗", stop_reason: null }),
        agentMessageFixture({
          entry_id: "a1",
          role: "assistant",
          content: "p 值为 0.099。",
          stop_reason: "revised",
          numeric_check: { unverified: [{ text: "0.099", closest: ["0.098491234"], kind: "number" }] },
        }),
        agentMessageFixture({ entry_id: "a2", role: "assistant", content: "p 值为 0.098。", stop_reason: "stop" }),
      ],
    });

    render(
      <AgentSurfaceContext.Provider value={withDraft}>
        <AgentPanel runId="run-a" projectRoot="/proj" />
      </AgentSurfaceContext.Provider>,
    );

    const reasoning = screen.getByTestId("agent-reasoning-u1");
    expect(reasoning).toContainElement(screen.getByTestId("agent-withdrawn-draft"));
    expect(screen.getByTestId("agent-withdrawn-draft")).toHaveTextContent(
      "Earlier draft, withdrawn by the number check: 0.099 matched no result",
    );
    expect(reasoning).not.toContainElement(screen.getByText("p 值为 0.098。"));
    expect(reasoning).toHaveTextContent("1 draft rewritten");
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
    withMessageLink.messages = [agentMessageFixture({
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
    })];

    render(
      <AgentSurfaceContext.Provider value={withMessageLink}>
        <AgentPanel runId="run-a" projectRoot="/proj" />
      </AgentSurfaceContext.Provider>,
    );

    const fork = screen.getByRole("button", { name: "Fork from Agent message u1" });
    expect(screen.getByRole("toolbar", { name: "Message actions" })).toContainElement(fork);
    expect(screen.queryByText("↳ Fork Agent context")).not.toBeInTheDocument();
    fireEvent.click(fork);
    expect(forkFromMessage).toHaveBeenCalledWith(
      "u1",
      expect.objectContaining({ kind: "graph_node", id: "run-a::model:ols_1" }),
    );
  });

  it("keeps a recorded tool row compact while preserving its eight references and both fork actions on disclosure", () => {
    const openNavigation = vi.fn();
    const forkConversation = vi.fn();
    const forkFromMessage = vi.fn();
    render(<AgentSurfaceContext.Provider value={value({ openNavigation, forkConversation, forkFromMessage, messages: [
      agentMessageFixture({ entry_id: "tool-recorded", role: "tool", name: "inspect_completed_operations", content: '{"ok":true}', navigation: recordedToolNavigation }),
    ] })}>
      <AgentPanel runId="run-a" projectRoot="/proj" />
    </AgentSurfaceContext.Provider>);
    const tool = screen.getByTestId("agent-message-tool");
    const summary = tool.querySelector<HTMLElement>("summary")!;
    const details = summary.closest("details");
    expect(details).not.toHaveAttribute("open");
    expect(tool).toHaveTextContent("Listed completed operations");
    expect(within(tool).getByRole("toolbar", { name: "Message actions", hidden: true })).not.toBeVisible();
    expect(tool.querySelectorAll(".wb-agent-message-link")).toHaveLength(8);
    tool.querySelectorAll(".wb-agent-message-link").forEach(link => expect(link).not.toBeVisible());

    fireEvent.click(summary);
    expect(details).toHaveAttribute("open");
    expect(within(tool).getByRole("toolbar", { name: "Message actions" })).toBeVisible();
    tool.querySelectorAll(".wb-agent-message-link").forEach(link => expect(link).toBeVisible());
    fireEvent.click(within(tool).getByRole("button", { name: "Open source model:ols_1" }));
    expect(openNavigation).toHaveBeenCalledWith(recordedToolNavigation[1]);
    fireEvent.click(within(tool).getByRole("button", { name: "Fork from here" }));
    expect(forkConversation).toHaveBeenCalledWith("tool-recorded");
    fireEvent.click(within(tool).getByRole("button", { name: "Fork from Agent message tool-recorded" }));
    expect(forkFromMessage).toHaveBeenCalledWith("tool-recorded", recordedToolNavigation[1]);
  });

  it("shows a disclosed tool toolbar without hover or focus while ordinary message actions stay quiet", () => {
    const style = document.createElement("style");
    style.textContent = readFileSync("src/workbench/agent/agent.css", "utf8");
    document.head.append(style);
    try {
      render(<AgentSurfaceContext.Provider value={value({ forkConversation: vi.fn(), messages: [
        agentMessageFixture({ entry_id: "tool-styled", role: "tool", name: "inspect_completed_operations", content: '{"ok":true}', navigation: recordedToolNavigation }),
        agentMessageFixture({ entry_id: "answer-styled", role: "assistant", content: "The receipt is recorded.", stop_reason: "stop", navigation: recordedToolNavigation }),
      ] })}>
        <AgentPanel runId="run-a" projectRoot="/proj" />
      </AgentSurfaceContext.Provider>);
      const tool = screen.getByTestId("agent-message-tool");
      const toolbar = within(tool).getByRole("toolbar", { name: "Message actions", hidden: true });
      const ordinaryToolbar = within(screen.getByTestId("agent-message-assistant")).getByRole("toolbar", { name: "Message actions", hidden: true });
      expect(toolbar).not.toBeVisible();
      expect(getComputedStyle(ordinaryToolbar).opacity).toBe("0");

      fireEvent.click(tool.querySelector<HTMLElement>("summary")!);
      expect(toolbar.parentElement).toHaveAttribute("open");
      expect(toolbar.contains(document.activeElement)).toBe(false);
      expect(getComputedStyle(toolbar).opacity).toBe("1");
      expect(toolbar).toBeVisible();
      expect(getComputedStyle(ordinaryToolbar).opacity).toBe("0");
      const toolLinks = tool.querySelector<HTMLElement>(".wb-agent-tool-details > .wb-agent-message-links")!;
      const toolLinksStyle = getComputedStyle(toolLinks);
      expect(toolLinksStyle.display).toBe("flex");
      expect(toolLinksStyle.width).toBe("100%");
      expect(toolLinksStyle.maxWidth).toBe("100%");
      expect(toolLinksStyle.flexWrap).toBe("wrap");
      expect(["hidden", "clip"]).not.toContain(toolLinksStyle.overflowX);
      expect(toolLinks.querySelectorAll(".wb-agent-message-link")).toHaveLength(8);
      toolLinks.querySelectorAll(".wb-agent-message-link").forEach(link => expect(link).toBeVisible());
      const ordinaryLinks = screen.getByTestId("agent-message-assistant").querySelector<HTMLElement>(":scope > .wb-agent-message-links")!;
      expect(getComputedStyle(ordinaryLinks).display).toBe("inline-flex");
    } finally {
      style.remove();
    }
  });

  it("keeps a failed receipt's public explanation visible with its controls collapsed", () => {
    render(<AgentSurfaceContext.Provider value={value({ messages: [
      agentMessageFixture({ entry_id: "failed-tool", role: "tool", name: "inspect_model_result", navigation: recordedToolNavigation,
        content: JSON.stringify({ ok: false, error: "RESULT_UNAVAILABLE", error_details: [{ message: "The recorded artifact is missing." }] }) }),
    ] })}>
      <AgentPanel runId="run-a" projectRoot="/proj" />
    </AgentSurfaceContext.Provider>);
    const tool = screen.getByTestId("agent-message-tool");
    expect(within(tool).getByText(/The recorded artifact is missing/)).toBeVisible();
    expect(tool.querySelector<HTMLElement>("summary")!.closest("details")).not.toHaveAttribute("open");
  });

  it("keeps a tool's context fork in its message actions with the source binding", () => {
    const forkFromMessage = vi.fn();
    const source: AgentNavigationRef = {
      kind: "graph_node", id: "run-a::model:ols_1", label: "Source model:ols_1", relation: "source",
      available: true, href: { view: "graph", run_id: "run-a", node_ref: "model:ols_1" },
    };
    render(<AgentSurfaceContext.Provider value={value({ forkFromMessage, messages: [
      agentMessageFixture({ entry_id: "t1", role: "tool", name: "inspect_node_context", content: '{"ok":true}', navigation: [source] }),
    ] })}>
      <AgentPanel runId="run-a" projectRoot="/proj" />
    </AgentSurfaceContext.Provider>);
    const tool = screen.getByTestId("agent-message-tool");
    expect(tool).not.toHaveTextContent("Tool receipt");
    fireEvent.click(tool.querySelector<HTMLElement>("summary")!);
    const fork = within(tool).getByRole("button", { name: "Fork from Agent message t1" });
    expect(within(tool).getByRole("toolbar", { name: "Message actions" })).toContainElement(fork);
    fireEvent.click(fork);
    expect(forkFromMessage).toHaveBeenCalledWith("t1", source);
  });

  it("retains the reason a source context cannot be forked", () => {
    render(<AgentSurfaceContext.Provider value={value({ messages: [agentMessageFixture({
      entry_id: "t1", role: "tool", content: '{"ok":true}', navigation: [{
        kind: "graph_node", id: "missing", label: "Source missing", relation: "source", available: false,
        reason: "The source node is no longer available", href: { view: "graph", run_id: "run-a" },
      }],
    })] })}>
      <AgentPanel runId="run-a" projectRoot="/proj" />
    </AgentSurfaceContext.Provider>);
    fireEvent.click(screen.getByTestId("agent-message-tool").querySelector<HTMLElement>("summary")!);
    const fork = screen.getByRole("button", { name: "Fork from Agent message t1" });
    expect(fork).toBeDisabled();
    expect(fork).toHaveAttribute("title", "The source node is no longer available");
  });

  it("folds dense references without discarding unavailable links or their reasons", () => {
    const openNavigation = vi.fn();
    const navigation: AgentNavigationRef[] = Array.from({ length: 8 }, (_, index) => ({
      kind: "run", id: `result-${index}`, label: `Result artifact ${index}`, relation: "result",
      available: index !== 7, reason: index === 7 ? "Artifact was removed" : undefined,
      href: { view: "graph", run_id: "run-a" },
    }));
    render(<AgentSurfaceContext.Provider value={value({ openNavigation, messages: [
      agentMessageFixture({ entry_id: "a1", role: "assistant", content: "Results are recorded.", navigation }),
    ] })}>
      <AgentPanel runId="run-a" projectRoot="/proj" />
    </AgentSurfaceContext.Provider>);
    const disclosure = screen.getByText("6 more references").closest("details");
    expect(disclosure).not.toHaveAttribute("open");
    fireEvent.click(screen.getByText("6 more references"));
    const last = screen.getByRole("button", { name: "Open result artifact 7", hidden: true });
    expect(last).toBeDisabled();
    expect(last).toHaveAttribute("title", "Artifact was removed");
    const link = screen.getByRole("button", { name: "Open result artifact 6", hidden: true });
    fireEvent.click(link);
    expect(openNavigation).toHaveBeenCalledWith(navigation[6]);
  });

  it("projects tool messages as typed status lines, not raw JSON dumps", () => {
    const withTool = value();
    withTool.messages = [
      agentMessageFixture({ entry_id: "u1", role: "user", content: "检查节点", stop_reason: null }),
      agentMessageFixture({
        entry_id: "t1",
        role: "tool",
        name: "inspect_node_context",
        content: JSON.stringify({
          error: null,
          ok: true,
          output: { context_version: "node-operation-context/v1", owner_run_id: "run-a" },
        }),
        stop_reason: null,
      }),
      agentMessageFixture({
        entry_id: "t2",
        role: "tool",
        name: "propose_operation",
        content: JSON.stringify({
          error: null,
          ok: true,
          output: { requires_confirmation: true, proposal: { proposal_id: "p-1" } },
        }),
        stop_reason: null,
      }),
      agentMessageFixture({
        entry_id: "t3",
        role: "tool",
        name: "inspect_diagnostics",
        content: JSON.stringify({
          output: null,
          ok: false,
          error: "tool_runtime_error",
        }),
        stop_reason: null,
      }),
    ];
    render(
      <AgentSurfaceContext.Provider value={withTool}>
        <AgentPanel runId="run-a" projectRoot="/proj" />
      </AgentSurfaceContext.Provider>,
    );

    const toolLines = screen.getAllByTestId("agent-message-tool");
    expect(toolLines[0]).toHaveTextContent("Read node context");
        expect(toolLines[0]).not.toHaveTextContent("node-operation-context/v1");
    expect(toolLines[1]).toHaveTextContent(/Waiting for your confirmation/);
    expect(toolLines[2]).toHaveTextContent("Read diagnostics");
    expect(toolLines[2]).toHaveTextContent("tool_runtime_error");
  });

  it("keeps an explicit empty state when no turn has started", () => {
    render(
      <AgentSurfaceContext.Provider value={{ ...value(), messages: [] }}>
        <AgentPanel runId="run-a" projectRoot="/proj" />
      </AgentSurfaceContext.Provider>,
    );
    expect(screen.getByTestId("agent-empty")).toBeEmptyDOMElement();
  });

  it("renders a pending proposal as an explicit confirmation card", () => {
    const withProposal = value();
    withProposal.proposals = [agentProposalFixture({
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
    })];
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
    withProposal.proposals = [agentProposalFixture({
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
    })];

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
    withProposal.proposals = [agentProposalFixture({
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
    })];
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

    const link = screen.getByRole("link", { name: "Agent audit" });
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
      messages: [agentMessageFixture({
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
      })],
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
    withMessageLink.messages = [agentMessageFixture({
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
    })];

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
    withProposal.proposals = [agentProposalFixture({
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
    })];
    render(
      <AgentSurfaceContext.Provider value={withProposal}>
        <AgentPanel runId="run-a" projectRoot="/proj" />
      </AgentSurfaceContext.Provider>,
    );

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Decline proposal proposal-1" }));
    });
    await waitFor(() => {
      expect(declineProposal).toHaveBeenCalledWith("proposal-1");
    });

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Revise proposal proposal-1" }));
    });
    expect(screen.getByRole("button", { name: "Confirm proposal proposal-1" })).toBeDisabled();
    const editor = screen.getByLabelText("Proposal changes proposal-1.covariance.new");
    await act(async () => {
      fireEvent.change(editor, {
        target: { value: "unadjusted" },
      });
      fireEvent.click(screen.getByRole("button", { name: "Save revision proposal-1" }));
    });
    await waitFor(() => {
      expect(reviseProposal).toHaveBeenCalledWith(
        "proposal-1",
        1,
        { covariance: { old: "nonrobust", new: "unadjusted" } },
      );
    });
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
      agentMessageFixture({ entry_id: "a-md", role: "assistant", content: "## Findings\n\n**Stable** result", stop_reason: "stop" }),
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


describe("AgentPanel target correction", () => {
  it("keeps the generated correction visible outside collapsed reasoning and uses the ordinary composer path", () => {
    const send = vi.fn();
    const confirm = vi.fn();
    const prompt = "Keep coef:control. Draft a correction plan; do not execute a substitute.";
    const state = value({ sendPrompt: send, confirmProposal: confirm, messages: [
      agentMessageFixture({ entry_id: "target-question", role: "user", content: "Analyze the control effect", stop_reason: null }),
      agentMessageFixture({ entry_id: "target-error", role: "tool", name: "run_operation", content: JSON.stringify({
        ok: false, error: "ANALYSIS_TARGET_CONFLICT", output: { status: "needs_target_decision", executed: false, recovery: {
          schema: "workbench.analysis-target-recovery.v1", source_run_id: "source-a",
          requested_result_id: "coef:control", primary_result_id: "coef:treatment",
          message: "Nothing was submitted or executed.", steps: ["Review the source", "Draft options", "Continue independent steps"],
          options: [{ id: "preserve_requested_target", label: "Keep requested target; review compatible sources", prompt }],
        } },
      }), stop_reason: null }),
      agentMessageFixture({ entry_id: "target-answer", role: "assistant", content: "Choose the target before dependent estimation.", stop_reason: "stop" }),
    ] });
    render(<AgentSurfaceContext.Provider value={state}><AgentPanel runId="source-a" projectRoot="/tmp/recovery-project" /></AgentSurfaceContext.Provider>);
    const notice = screen.getByRole("status", { name: "Analysis target correction" });
    expect(notice.closest("details")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Keep requested target; review compatible sources" }));
    expect(send).toHaveBeenCalledTimes(1);
    expect(send).toHaveBeenCalledWith(prompt);
    expect(confirm).not.toHaveBeenCalled();
  });
});

describe("Agent recorded usage", () => {
  const observation = (seq:number, payload:Record<string,unknown>) => ({
    schema_version:"agent.event.v1",event_id:`usage-${seq}`,session_id:"session",seq,event_type:"provider_step",
    command_id:"command",created_at:"2026-10-20T17:00:00Z",payload:{request_id:`request-${seq}`,provider_step:seq,
      model:"test-model",usage_scope:"last_reported_snapshot",usage_state:"reported",outcome:"stop",retries:0,
      elapsed_s:1.25,first_public_s:0.2,cost:null,cost_state:"pricing_unverified",...payload},
  });
  it("shows per-step timing, tokens, weighted cache usage and unverified cost", () => {
    render(<AgentSurfaceContext.Provider value={value({providerSteps:[
      observation(1,{usage:{prompt_tokens:80,completion_tokens:9,prompt_cache_hit_tokens:60}}),
      observation(2,{usage:{prompt_tokens:20,completion_tokens:2,prompt_cache_hit_tokens:0},outcome:"error",retries:1}),
    ]})}><AgentPanel runId="run-a" projectRoot="/proj" /></AgentSurfaceContext.Provider>);
    const usage=screen.getByTestId("agent-usage");
    expect(usage).toHaveTextContent("2 provider steps");
    expect(usage).toHaveTextContent("100 input");
    expect(usage).toHaveTextContent("11 output");
    expect(usage).toHaveTextContent("60.0% cache");
    expect(usage).toHaveTextContent("1.25s");
    expect(usage).toHaveTextContent("0.20s");
    expect(usage).toHaveTextContent("error");
    expect(usage).toHaveTextContent("Cost unverified");
  });
  it("keeps missing and invalid usage unknown and preserves failed or cancelled calls", () => {
    render(<AgentSurfaceContext.Provider value={value({providerSteps:[
      observation(1,{usage:null,usage_state:"unavailable",outcome:"cancelled"}),
      observation(2,{usage:{prompt_tokens:-20,completion_tokens:"9",prompt_cache_hit_tokens:90}}),
    ]})}><AgentPanel runId="run-a" projectRoot="/proj" /></AgentSurfaceContext.Provider>);
    const usage=screen.getByTestId("agent-usage");
    expect(usage).toHaveTextContent("Input unavailable");
    expect(usage).toHaveTextContent("Output unavailable");
    expect(usage).toHaveTextContent("Cache unavailable");
    expect(usage).toHaveTextContent("cancelled");
    expect(usage).not.toHaveTextContent("0 input");
  });
  it("does not imply an empty usage log means zero cost", () => {
    render(<AgentSurfaceContext.Provider value={value()}><AgentPanel runId="run-a" projectRoot="/proj" /></AgentSurfaceContext.Provider>);
    expect(screen.queryByTestId("agent-usage")).not.toBeInTheDocument();
  });

  it("folds the model's thinking beside the step that followed it", () => {
    render(<AgentSurfaceContext.Provider value={value({messages: [
      agentMessageFixture({entry_id: "u1", role: "user", content: "Why?"}),
      agentMessageFixture({entry_id: "a1", role: "assistant", content: "Because.", stop_reason: "stop", reasoning: "Check the residuals first."}),
    ]})}><AgentPanel runId="run-a" projectRoot="/proj" /></AgentSurfaceContext.Provider>);
    const thinking = screen.getByTestId("agent-thinking");
    expect(thinking).not.toHaveAttribute("open");
    expect(thinking).toHaveTextContent("Check the residuals first.");
  });
});
