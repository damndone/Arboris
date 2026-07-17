import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AgentPanel } from "./AgentPanel";
import { AgentSurfaceProvider } from "./AgentSurfaceContext";
import type { AgentMessage, AgentProposal } from "./agentTypes";

const mocks = vi.hoisted(() => ({
  createAgentSession: vi.fn(),
  confirmAgentProposal: vi.fn(),
  declineAgentProposal: vi.fn(),
  reviseAgentProposal: vi.fn(),
  reconcileAgentOperation: vi.fn(),
  getAgentOperationProjection: vi.fn(),
  getAgentSession: vi.fn(),
  getAgentSessionProjection: vi.fn(),
  getAgentEvents: vi.fn(),
  getAgentCapabilities: vi.fn(),
  sendAgentTurn: vi.fn(),
  fetchLlmProviders: vi.fn(),
  fetchLlmConfig: vi.fn(),
  updateLlmProvider: vi.fn(),
  lineageModel: { current: { nodes: [] } as Record<string, unknown> },
  workbenchState: { selectedKey: null as string | null },
}));

vi.mock("./agentApi", () => ({
  createAgentSession: mocks.createAgentSession,
  confirmAgentProposal: mocks.confirmAgentProposal,
  declineAgentProposal: mocks.declineAgentProposal,
  reviseAgentProposal: mocks.reviseAgentProposal,
  reconcileAgentOperation: mocks.reconcileAgentOperation,
  getAgentOperationProjection: mocks.getAgentOperationProjection,
  getAgentSession: mocks.getAgentSession,
  getAgentSessionProjection: mocks.getAgentSessionProjection,
  getAgentEvents: mocks.getAgentEvents,
  getAgentCapabilities: mocks.getAgentCapabilities,
  sendAgentTurn: mocks.sendAgentTurn,
  fallbackProjectContext: (runId: string, selectedKey: string | null) => ({
    packet_version: "agent-context/v1",
    context_fingerprint: `project:${runId}:${selectedKey ?? "none"}`,
  }),
}));
vi.mock("../../llm/llmApi", () => ({
  fetchLlmProviders: mocks.fetchLlmProviders,
  fetchLlmConfig: mocks.fetchLlmConfig,
  updateLlmProvider: mocks.updateLlmProvider,
}));
vi.mock("../../lineage/LineageContext", () => ({
  useLineage: () => ({ model: mocks.lineageModel.current, selectedKey: null, select: vi.fn() }),
}));
vi.mock("../ForestContext", () => ({ useForest: () => null }));
vi.mock("../WorkbenchStateProvider", () => ({
  useWorkbench: () => ({ state: mocks.workbenchState }),
}));

const provider = {
  id: "deepseek",
  name: "DeepSeek",
  icon: "",
  notes: "",
  website_url: null,
  base_url: "https://api.deepseek.com",
  model: "deepseek-v4-flash",
  timeout_s: 120,
  key_present: true,
  models: [
    { display_name: "DeepSeek V4 Flash", request_model: "deepseek-v4-flash", context_window_tokens: 32000, supports_1m: false },
    { display_name: "DeepSeek Chat", request_model: "deepseek-chat", context_window_tokens: 64000, supports_1m: false },
  ],
};

const config = {
  configured: true,
  base_url: provider.base_url,
  model: provider.model,
  key_present: true,
  timeout_s: 120,
  provider_id: provider.id,
  provider_name: provider.name,
  source: "local" as const,
  context_window_tokens: 32000,
  supports_1m: false,
};

const pendingProposal: AgentProposal = {
  record_type: "revision" as const,
  proposal_id: "proposal-1",
  operation_id: "model.rerun",
  operation_version: "v1",
  revision: 1,
  session_id: "agent_chain_saved",
  chain_id: "chain:run-a",
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
};

function session(
  sessionId: string,
  messages: AgentMessage[] = [],
  proposals: AgentProposal[] = [],
) {
  return {
    session_id: sessionId,
    role: "chain" as const,
    chain_id: "chain:run-a",
    status: "idle",
    context_fingerprint: "fp",
    model: provider.model,
    provider_id: provider.id,
    context_window_tokens: 32000,
    messages,
    proposals,
  };
}

function mount() {
  return render(
    <MemoryRouter>
      <AgentSurfaceProvider projectRoot="/proj" runId="run-a">
        <AgentPanel projectRoot="/proj" runId="run-a" />
      </AgentSurfaceProvider>
    </MemoryRouter>,
  );
}

describe("AgentSurfaceProvider", () => {
  beforeEach(() => {
    sessionStorage.clear();
    vi.clearAllMocks();
    mocks.lineageModel.current = { nodes: [] };
    mocks.workbenchState.selectedKey = null;
    mocks.fetchLlmProviders.mockResolvedValue({ active_provider_id: provider.id, providers: [provider] });
    mocks.fetchLlmConfig.mockResolvedValue(config);
    mocks.getAgentEvents.mockResolvedValue({ events: [] });
    mocks.getAgentCapabilities.mockResolvedValue({
      capabilities: [],
      boundary: { advisory: [], unsupported: [] },
    });
    mocks.getAgentSessionProjection.mockResolvedValue({
      projection: { subject: { kind: "agent_session", id: "session", label: "Agent session", relation: "context", available: true, href: { view: "agent", session_id: "session" } }, links: [], last_event_seq: 0 },
    });
    mocks.getAgentOperationProjection.mockResolvedValue({
      operation: {
        record_id: "record-1",
        operation_id: "model.rerun",
        proposal_id: "proposal-1",
        status: "completed",
        outputs: { target_run_id: "run-child" },
        diff_ref: { kind: "canonical", changed: ["covariance"] },
        verification: { passed: true },
      },
      projection: { subject: { kind: "operation", id: "record-1", label: "model.rerun", relation: "audit", available: true, href: { view: "agent", operation_record_id: "record-1" } }, links: [], last_event_seq: 0 },
    });
    mocks.updateLlmProvider.mockResolvedValue({ ...provider, model: "deepseek-chat" });
    mocks.createAgentSession.mockResolvedValue(session("agent_chain_new"));
    mocks.sendAgentTurn.mockResolvedValue({
      session: session("agent_chain_new", [
        { entry_id: "u1", role: "user", content: "检查这个图" },
        { entry_id: "a1", role: "assistant", content: "已检查 active head。", stop_reason: "stop" },
      ]),
      assistant: { entry_id: "a1", role: "assistant", content: "已检查 active head。" },
      status: "idle",
    });
    mocks.confirmAgentProposal.mockResolvedValue({
      proposal: { ...pendingProposal, status: "confirmed" },
      operation: { record_id: "record-1", operation_id: "model.rerun", proposal_id: "proposal-1", status: "pending" },
      status: "pending",
    });
    mocks.declineAgentProposal.mockResolvedValue({
      proposal: { ...pendingProposal, status: "declined" },
      status: "declined",
    });
    mocks.reviseAgentProposal.mockResolvedValue({
      proposal: { ...pendingProposal, revision: 2, status: "pending" },
      status: "pending",
    });
  });

  it("shares model selection and a submitted turn across the panel surface", async () => {
    mount();

    const model = await screen.findByRole("listbox", { name: "Agent model" });
    expect(model).toHaveValue("deepseek-v4-flash");
    fireEvent.change(model, { target: { value: "deepseek-chat" } });
    await waitFor(() => expect(mocks.updateLlmProvider).toHaveBeenCalledWith("deepseek", { model: "deepseek-chat" }));

    fireEvent.change(screen.getByRole("textbox", { name: "Ask Agent" }), { target: { value: "检查这个图" } });
    fireEvent.click(screen.getByRole("button", { name: "Send to Agent" }));
    await waitFor(() => expect(mocks.createAgentSession).toHaveBeenCalledWith("/proj", expect.objectContaining({
      role: "chain",
      run_id: "run-a",
      context_packet: expect.objectContaining({ packet_version: "agent-context/v1" }),
    })));
    await waitFor(() => expect(screen.getByText("已检查 active head。")).toBeInTheDocument());
  });

  it("hydrates a durable session after reload", async () => {
    sessionStorage.setItem(
      "workbench:agent-session:/proj:run-a:project%3Arun-a%3Anone",
      "agent_chain_saved",
    );
    mocks.getAgentSession.mockResolvedValue(session("agent_chain_saved", [
      { entry_id: "a1", role: "assistant", content: "可回放的回答。", stop_reason: "stop" },
    ]));

    mount();

    await waitFor(() => expect(mocks.getAgentSession).toHaveBeenCalledWith("/proj", "agent_chain_saved"));
    expect(await screen.findByText("可回放的回答。")).toBeInTheDocument();
  });

  it("hydrates typed Main/Chain/fork navigation links with the durable session", async () => {
    sessionStorage.setItem(
      "workbench:agent-session:/proj:run-a:project%3Arun-a%3Anone",
      "agent_chain_saved",
    );
    mocks.getAgentSession.mockResolvedValue(session("agent_chain_saved"));
    mocks.getAgentSessionProjection.mockResolvedValue({
      projection: {
        subject: {
          kind: "agent_session",
          id: "agent_chain_saved",
          label: "Agent agent_chain_saved",
          relation: "context",
          available: true,
          href: { view: "agent", session_id: "agent_chain_saved" },
        },
        links: [{
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
        last_event_seq: 4,
      },
    });

    mount();

    await waitFor(() => expect(mocks.getAgentSessionProjection).toHaveBeenCalledWith(
      "/proj",
      "agent_chain_saved",
    ));
    expect(await screen.findByRole("button", { name: /open source model/i })).toBeInTheDocument();
  });

  it("loads a linked child Agent session and operation focus from the URL", async () => {
    mocks.getAgentSession.mockResolvedValue(session("agent_child"));

    render(
      <MemoryRouter initialEntries={["/?panel=agent&agent_session=agent_child&operation=record-1&diff=1"]}>
        <AgentSurfaceProvider projectRoot="/proj" runId="run-a">
          <AgentPanel projectRoot="/proj" runId="run-a" />
        </AgentSurfaceProvider>
      </MemoryRouter>,
    );

    await waitFor(() => expect(mocks.getAgentSession).toHaveBeenCalledWith(
      "/proj",
      "agent_child",
    ));
    await waitFor(() => expect(mocks.getAgentOperationProjection).toHaveBeenCalledWith(
      "/proj",
      "agent_child",
      "record-1",
    ));
    expect(await screen.findByTestId("agent-operation-status")).toHaveTextContent(
      "completed",
    );
    expect(screen.getByTestId("agent-operation-status")).toHaveTextContent("run-child");
    expect(screen.getByTestId("agent-operation-diff")).toHaveTextContent("canonical");
    expect(screen.getByTestId("agent-operation-diff")).toHaveTextContent("covariance");
  });

  it("replays durable events and exposes the latest event cursor", async () => {
    sessionStorage.setItem(
      "workbench:agent-session:/proj:run-a:project%3Arun-a%3Anone",
      "agent_chain_saved",
    );
    mocks.getAgentSession.mockResolvedValue(session("agent_chain_saved"));
    mocks.getAgentEvents.mockResolvedValue({
      events: [
        {
          event_id: "event-3",
          session_id: "agent_chain_saved",
          seq: 3,
          event_type: "tool_execution_end",
          payload: { tool_id: "inspect_node_context", ok: true },
          command_id: "command-1",
          created_at: "2026-07-14T00:00:00Z",
        },
        {
          event_id: "event-7",
          session_id: "agent_chain_saved",
          seq: 7,
          event_type: "agent_end",
          payload: { stop_reason: "stop" },
          command_id: "command-1",
          created_at: "2026-07-14T00:00:01Z",
        },
      ],
    });

    mount();

    await waitFor(() => expect(mocks.getAgentEvents).toHaveBeenCalledWith(
      "/proj",
      "agent_chain_saved",
      0,
    ));
    expect(await screen.findByTestId("agent-event-cursor")).toHaveTextContent("events #7");
  });

  it("rebinds the session when the selected-node context changes", async () => {
    mocks.workbenchState.selectedKey = "node:old";
    sessionStorage.setItem(
      "workbench:agent-session:/proj:run-a:project%3Arun-a%3Anode%3Aold",
      "agent_chain_old",
    );
    mocks.getAgentSession.mockResolvedValue({
      ...session("agent_chain_old"),
      messages: [{ entry_id: "old", role: "assistant", content: "旧节点回答。" }],
    });

    const rendered = mount();
    expect(await screen.findByText("旧节点回答。")).toBeInTheDocument();

    mocks.workbenchState.selectedKey = "node:new";
    rendered.rerender(
      <MemoryRouter>
        <AgentSurfaceProvider projectRoot="/proj" runId="run-a">
          <AgentPanel projectRoot="/proj" runId="run-a" />
        </AgentSurfaceProvider>
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.queryByText("旧节点回答。")).not.toBeInTheDocument());
    fireEvent.change(screen.getByRole("textbox", { name: "Ask Agent" }), {
      target: { value: "检查新节点" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send to Agent" }));
    await waitFor(() => expect(mocks.createAgentSession).toHaveBeenCalledWith(
      "/proj",
      expect.objectContaining({
        run_id: "run-a",
        context_packet: expect.objectContaining({
          context_fingerprint: "project:run-a:node:new",
        }),
      }),
    ));
  });

  it("includes the unsent prompt in the visible context estimate", async () => {
    mount();
    const ring = await screen.findByTestId("agent-context-ring");
    const before = await ring.getAttribute("aria-label");
    fireEvent.change(screen.getByRole("textbox", { name: "Ask Agent" }), {
      target: { value: "x".repeat(400) },
    });
    await waitFor(async () => expect(await ring.getAttribute("aria-label")).not.toBe(before));
  });

  it("does not crash when a legacy lineage model has no nodes collection", async () => {
    mocks.lineageModel.current = {};

    mount();

    expect(await screen.findByTestId("agent-panel")).toBeInTheDocument();
  });

  it("does not crash when legacy LLM endpoints return an incomplete payload", async () => {
    mocks.fetchLlmProviders.mockResolvedValue({});
    mocks.fetchLlmConfig.mockResolvedValue({});

    mount();

    expect(await screen.findByTestId("agent-panel")).toBeInTheDocument();
  });

  it("confirms a visible proposal with the current active head", async () => {
    sessionStorage.setItem(
      "workbench:agent-session:/proj:run-a:project%3Arun-a%3Anone",
      "agent_chain_saved",
    );
    mocks.getAgentSession.mockResolvedValue(session("agent_chain_saved", [], [pendingProposal]));

    mount();

    const button = await screen.findByRole("button", { name: "Confirm proposal proposal-1" });
    fireEvent.click(button);
    await waitFor(() => expect(mocks.confirmAgentProposal).toHaveBeenCalledWith(
      "/proj",
      "agent_chain_saved",
      "proposal-1",
      { revision: 1, fingerprint: "fingerprint-1", active_head_run_id: "run-a" },
    ));
    expect(await screen.findByText("confirmed")).toBeInTheDocument();
  });

  it("declines a visible proposal through the scoped Agent API", async () => {
    sessionStorage.setItem(
      "workbench:agent-session:/proj:run-a:project%3Arun-a%3Anone",
      "agent_chain_saved",
    );
    mocks.getAgentSession.mockResolvedValue(session("agent_chain_saved", [], [pendingProposal]));

    mount();

    fireEvent.click(await screen.findByRole("button", { name: "Decline proposal proposal-1" }));
    await waitFor(() => expect(mocks.declineAgentProposal).toHaveBeenCalledWith(
      "/proj",
      "agent_chain_saved",
      "proposal-1",
      undefined,
    ));
    expect(await screen.findByText("declined")).toBeInTheDocument();
  });

  it("revises a visible proposal through the scoped Agent API", async () => {
    sessionStorage.setItem(
      "workbench:agent-session:/proj:run-a:project%3Arun-a%3Anone",
      "agent_chain_saved",
    );
    mocks.getAgentSession.mockResolvedValue(session("agent_chain_saved", [], [pendingProposal]));

    mount();

    fireEvent.click(await screen.findByRole("button", { name: "Revise proposal proposal-1" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Proposal changes proposal-1" }), {
      target: { value: '{"covariance":{"old":"nonrobust","new":"unadjusted"}}' },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save revision proposal-1" }));
    await waitFor(() => expect(mocks.reviseAgentProposal).toHaveBeenCalledWith(
      "/proj",
      "agent_chain_saved",
      "proposal-1",
      {
        base_revision: 1,
        changes: { covariance: { old: "nonrobust", new: "unadjusted" } },
      },
    ));
    expect(await screen.findByText("revision 2")).toBeInTheDocument();
  });

  it("executes on confirm and polls reconcile until the operation completes", async () => {
    sessionStorage.setItem(
      "workbench:agent-session:/proj:run-a:project%3Arun-a%3Anone",
      "agent_chain_saved",
    );
    mocks.getAgentSession.mockResolvedValue(session("agent_chain_saved", [], [pendingProposal]));
    mocks.confirmAgentProposal.mockResolvedValue({
      proposal: { ...pendingProposal, status: "confirmed" },
      operation: {
        record_id: "record-1",
        operation_id: "model.rerun",
        proposal_id: "proposal-1",
        status: "running",
        outputs: { target_run_id: "run-child" },
      },
      status: "running",
    });
    mocks.reconcileAgentOperation
      .mockResolvedValueOnce({
        operation: {
          record_id: "record-1",
          operation_id: "model.rerun",
          proposal_id: "proposal-1",
          status: "running",
          outputs: { target_run_id: "run-child" },
        },
        status: "running",
      })
      .mockResolvedValue({
        operation: {
          record_id: "record-1",
          operation_id: "model.rerun",
          proposal_id: "proposal-1",
          status: "completed",
          outputs: { target_run_id: "run-child" },
        },
        status: "completed",
      });

    mount();

    const button = await screen.findByRole("button", { name: "Confirm proposal proposal-1" });
    fireEvent.click(button);

    // Confirmation executes: the running operation with its child run is
    // visible immediately, then reconcile polling drives it to completed.
    const status = await screen.findByTestId("agent-operation-status");
    expect(status).toHaveTextContent("model.rerun");
    expect(status).toHaveTextContent("run-child");
    await waitFor(
      () => expect(screen.getByTestId("agent-operation-status")).toHaveTextContent("completed"),
      { timeout: 6000 },
    );
    expect(mocks.reconcileAgentOperation).toHaveBeenCalledWith(
      "/proj",
      "agent_chain_saved",
      "record-1",
    );
  }, 10000);
});
