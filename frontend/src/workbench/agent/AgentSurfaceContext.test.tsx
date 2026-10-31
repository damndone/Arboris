import "@testing-library/jest-dom/vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AgentPanel } from "./AgentPanel";
import { AgentComposer } from "./AgentComposer";
import { AgentColumnComposer } from "../../workspace/agent/AgentColumnComposer";
import { AgentSurfaceProvider, useAgentSurface } from "./AgentSurfaceContext";
import type { AgentEvent, AgentMessage, AgentProposal } from "./agentTypes";
import { agentCapabilitiesFixture, agentMessageFixture, agentProposalFixture, operationCapabilityFixture } from "../../apiFixtures";
import { ApiError } from "../../api";

const mocks = vi.hoisted(() => ({
  rewindAgentSession: vi.fn(),
  setAgentFocus: vi.fn(),
  getAgentPlan: vi.fn(),
  getAgentPlanVerification: vi.fn(),
  forkAgentSession: vi.fn(),
  patchAgentPlan: vi.fn(),
  approveAgentPlan: vi.fn(),
  getAgentTurnState: vi.fn(),
  continueAgentTurn: vi.fn(),
  resumeAgentTurn: vi.fn(),
  queueAgentTurnMessage: vi.fn(),
  createAgentSession: vi.fn(),
  abortAgentTurn: vi.fn(),
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
  detectLlmProviderModels: vi.fn(() => Promise.reject(new Error("no listing"))),
  updateLlmProvider: vi.fn(),
  lineageModel: { current: { nodes: [] } as Record<string, unknown> },
  workbenchState: { selectedKey: null as string | null, agentFocus: null as null | { kind: "report" | "plan"; id: string; runId?: string } },
  forest: { current: null as unknown },
}));

vi.mock("./agentApi", () => ({
  rewindAgentSession: mocks.rewindAgentSession,
  getAgentPlan: mocks.getAgentPlan,
  getAgentPlanVerification: mocks.getAgentPlanVerification,
  forkAgentSession: mocks.forkAgentSession,
  patchAgentPlan: mocks.patchAgentPlan,
  approveAgentPlan: mocks.approveAgentPlan,
  getAgentTurnState: mocks.getAgentTurnState,
  continueAgentTurn: mocks.continueAgentTurn,
  resumeAgentTurn: mocks.resumeAgentTurn,
  queueAgentTurnMessage: mocks.queueAgentTurnMessage,
  createAgentSession: mocks.createAgentSession,
  abortAgentTurn: mocks.abortAgentTurn,
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
  detectLlmProviderModels: mocks.detectLlmProviderModels,
  updateLlmProvider: mocks.updateLlmProvider,
}));
vi.mock("../../lineage/LineageContext", () => ({
  useLineage: () => ({ model: mocks.lineageModel.current, selectedKey: null, select: vi.fn() }),
}));
vi.mock("../ForestContext", () => ({ useForest: () => mocks.forest.current }));
vi.mock("../WorkbenchStateProvider", () => ({
  useWorkbench: () => ({ state: mocks.workbenchState, dispatch: {setAgentFocus: mocks.setAgentFocus} }),
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

// Recorded public panel events, source SHA256 57740f6f70ab86042fc78cd728ba9275c17788398b1b7876c9b41cb0fcdc50a9.
const recordedParallelTools: AgentEvent[] = [
  {
    "command_id": "e297b5d9819548f9ab9721f4b6842cd1",
    "created_at": "2026-10-22T15:13:57.328833+00:00",
    "event_id": "336fa03c63624a3ba14c28c925e94b00",
    "event_type": "tool_execution_start",
    "payload": {
      "tool_call_id": "call_00_SXfJctHbpUGm7nHHDOi92645",
      "tool_id": "inspect_node_context"
    },
    "schema_version": "agent.event.v1",
    "seq": 7,
    "session_id": "agent_chain_f1913f9cdc864d56822cdbc22910bfb2"
  },
  {
    "command_id": "e297b5d9819548f9ab9721f4b6842cd1",
    "created_at": "2026-10-22T15:13:57.333332+00:00",
    "event_id": "1aae4d903e79403db08760d2a2ba9e77",
    "event_type": "tool_execution_start",
    "payload": {
      "tool_call_id": "call_01_4K6COsLkiRfe2McsPNkr4520",
      "tool_id": "inspect_data_schema"
    },
    "schema_version": "agent.event.v1",
    "seq": 8,
    "session_id": "agent_chain_f1913f9cdc864d56822cdbc22910bfb2"
  },
  {
    "command_id": "e297b5d9819548f9ab9721f4b6842cd1",
    "created_at": "2026-10-22T15:13:57.345274+00:00",
    "event_id": "724531c7b414435db6edc3d7c5fa356b",
    "event_type": "tool_execution_end",
    "payload": {
      "entry_id": "336315f1a6984dd7956bcb2cd69e2d62",
      "error": null,
      "ok": true,
      "tool_call_id": "call_00_SXfJctHbpUGm7nHHDOi92645",
      "tool_id": "inspect_node_context"
    },
    "schema_version": "agent.event.v1",
    "seq": 9,
    "session_id": "agent_chain_f1913f9cdc864d56822cdbc22910bfb2"
  },
  {
    "command_id": "e297b5d9819548f9ab9721f4b6842cd1",
    "created_at": "2026-10-22T15:13:57.349445+00:00",
    "event_id": "f38ae0fe61fb48c6b8580501d2bc8e4a",
    "event_type": "tool_execution_end",
    "payload": {
      "entry_id": "7248ab9ed16b4dc4b83ab6bc1fd07c7b",
      "error": null,
      "ok": true,
      "tool_call_id": "call_01_4K6COsLkiRfe2McsPNkr4520",
      "tool_id": "inspect_data_schema"
    },
    "schema_version": "agent.event.v1",
    "seq": 10,
    "session_id": "agent_chain_f1913f9cdc864d56822cdbc22910bfb2"
  }
];

const pendingProposal: AgentProposal = agentProposalFixture({
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
});

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
  afterEach(() => vi.mocked(window.confirm).mockRestore());
  beforeEach(() => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    sessionStorage.clear();
    localStorage.clear();
    vi.clearAllMocks();
    mocks.lineageModel.current = { nodes: [] };
    mocks.workbenchState.selectedKey = null;
    mocks.workbenchState.agentFocus = null;
    mocks.forest.current = null;
    mocks.fetchLlmProviders.mockResolvedValue({ active_provider_id: provider.id, providers: [provider] });
    mocks.fetchLlmConfig.mockResolvedValue(config);
    mocks.getAgentPlan.mockResolvedValue({plan:null,versions:[]});
    mocks.getAgentTurnState.mockResolvedValue({turns:[]});
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
    mocks.abortAgentTurn.mockResolvedValue({ status: "cancelling", session_id: "agent_chain_new" });
    mocks.sendAgentTurn.mockResolvedValue({
      session: session("agent_chain_new", [
        agentMessageFixture({ entry_id: "u1", role: "user", content: "检查这个图" }),
        agentMessageFixture({ entry_id: "a1", role: "assistant", content: "已检查 active head。", stop_reason: "stop" }),
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

  it("joint rewind switches to the restored branch, head and focus before the next request", async () => {
    mocks.getAgentSession.mockImplementation(async (_root,id) => session(id));
    mocks.rewindAgentSession.mockResolvedValue({session:session("restored"),restored_prompt:"Original",lineage:{run_id:"run-source",focus:{kind:"node",id:"node-source",run_id:"run-source"}}});
    const setActiveRunId=vi.fn();
    mocks.forest.current={forest:{nodes:[],heads:[]},activeRunId:"run-a",setActiveRunId};
    mount();
    fireEvent.change(screen.getByRole("textbox",{name:"Ask Agent"}),{target:{value:"Seed"}});
    fireEvent.click(screen.getByRole("button",{name:"Send to Agent"}));
    fireEvent.click(await screen.findByRole("button",{name:"Rewind to here"}));
    await waitFor(()=>expect(Object.values(localStorage)).toContain("restored"));
    expect(setActiveRunId).toHaveBeenCalledWith("run-source");
    expect(mocks.setAgentFocus).toHaveBeenCalledWith({kind:"node",id:"node-source",runId:"run-source"});
    await waitFor(()=>expect(mocks.getAgentPlan).toHaveBeenCalledWith("/proj","restored"));
    fireEvent.change(screen.getByRole("textbox",{name:"Ask Agent"}),{target:{value:"Revised request"}});
    fireEvent.click(screen.getByRole("button",{name:"Send to Agent"}));
    await waitFor(()=>expect(mocks.sendAgentTurn).toHaveBeenCalledWith("/proj","restored","Revised request",expect.any(AbortSignal),expect.anything(),"proposal_only","ask"));
    expect(mocks.continueAgentTurn).not.toHaveBeenCalled();
  });

  it("a refused joint rewind preserves the current conversation and its saved binding", async () => {
    const key="workbench:agent-session:/proj:run-a:project%3Arun-a%3Anone";
    localStorage.setItem(key,"old");
    mocks.getAgentSession.mockResolvedValue(session("old",[agentMessageFixture({entry_id:"u1",role:"user",content:"Keep this"})]));
    mocks.rewindAgentSession.mockRejectedValue(new Error("Stop the unfinished execution first."));
    mount();
    fireEvent.click(await screen.findByRole("button",{name:"Rewind to here"}));
    expect(await screen.findByText("Stop the unfinished execution first.")).toBeInTheDocument();
    expect(localStorage.getItem(key)).toBe("old");
    expect(screen.getByText("Keep this")).toBeInTheDocument();
    expect(mocks.setAgentFocus).not.toHaveBeenCalled();
  });

  it("ignores a joint rewind response after the user switches conversations", async () => {
    const keyA="workbench:agent-session:/proj:run-a:project%3Arun-a%3Anone";
    const keyB="workbench:agent-session:/proj:run-b:project%3Arun-b%3Anone";
    localStorage.setItem(keyA,"old");localStorage.setItem(keyB,"other");
    mocks.getAgentSession.mockImplementation(async (_root,id)=>session(id,[agentMessageFixture({entry_id:"u1",role:"user",content:id})]));
    let finish!: (value:unknown)=>void;
    mocks.rewindAgentSession.mockImplementation(()=>new Promise(resolve=>{finish=resolve;}));
    const view=mount();
    fireEvent.click(await screen.findByRole("button",{name:"Rewind to here"}));
    view.rerender(<MemoryRouter><AgentSurfaceProvider projectRoot="/proj" runId="run-b"><AgentPanel projectRoot="/proj" runId="run-b" /></AgentSurfaceProvider></MemoryRouter>);
    await screen.findByText("other");
    await act(async()=>finish({session:session("restored"),restored_prompt:"Undone",lineage:{run_id:"run-source",focus:null}}));
    expect(screen.getByText("other")).toBeInTheDocument();
    expect(localStorage.getItem(keyB)).toBe("other");
    expect(mocks.setAgentFocus).not.toHaveBeenCalled();
    expect(mocks.sendAgentTurn).not.toHaveBeenCalled();
  });

  it("replays recorded usage once and clears it when changing sessions", async () => {
    localStorage.setItem("workbench:agent-session:/proj:run-a:project%3Arun-a%3Anone","saved");
    localStorage.setItem("workbench:agent-session:/proj:run-b:project%3Arun-b%3Anone","other");
    mocks.getAgentSession.mockImplementation(async (_root,id)=>session(id));
    const event={schema_version:"agent.event.v1",event_id:"usage",session_id:"saved",seq:9,event_type:"provider_step",
      command_id:"command",created_at:"2026-10-20T17:00:00Z",payload:{request_id:"request",provider_step:1,model:"test-model",
        elapsed_s:1,first_public_s:0.2,outcome:"stop",retries:0,usage_state:"reported",usage_scope:"last_reported_snapshot",
        usage:{prompt_tokens:80,completion_tokens:9,prompt_cache_hit_tokens:60},cost:null,cost_state:"pricing_unverified"}};
    mocks.getAgentEvents.mockImplementation(async (_root,id)=>({events:id==="saved"?[event]:[]}));
    const view=mount();
    expect(await screen.findByTestId("agent-usage")).toHaveTextContent("1 provider steps");
    fireEvent.change(screen.getByRole("textbox",{name:"Ask Agent"}),{target:{value:"Another question"}});
    fireEvent.click(screen.getByRole("button",{name:"Send to Agent"}));
    await waitFor(()=>expect(mocks.getAgentEvents.mock.calls.length).toBeGreaterThan(1));
    expect(screen.getByTestId("agent-usage")).toHaveTextContent("80 input");
    expect(screen.getByTestId("agent-usage")).not.toHaveTextContent("160 input");
    view.rerender(<MemoryRouter><AgentSurfaceProvider projectRoot="/proj" runId="run-b"><AgentPanel projectRoot="/proj" runId="run-b" /></AgentSurfaceProvider></MemoryRouter>);
    await waitFor(()=>expect(mocks.getAgentPlan).toHaveBeenCalledWith("/proj","other"));
    expect(screen.queryByTestId("agent-usage")).not.toBeInTheDocument();
  });

  it("keeps the unfinished parallel inspection visible when a recorded receipt completes its sibling", async () => {
    const saved = recordedParallelTools[0].session_id;
    localStorage.setItem("workbench:agent-session:/proj:run-a:project%3Arun-a%3Anone", saved);
    mocks.getAgentSession.mockResolvedValue({ ...session(saved), status: "running" });
    let events = recordedParallelTools.slice(0, 2);
    mocks.getAgentEvents.mockImplementation(async () => ({ events }));
    mount();

    await waitFor(() => expect(screen.getByTestId("agent-event-cursor")).toHaveTextContent("events #8"));
    expect(screen.getByTestId("agent-execution-trace")).toHaveTextContent(" · ");
    expect(screen.getByTestId("agent-execution-trace")).toHaveTextContent("Read node context");
    expect(screen.getByTestId("agent-execution-trace")).toHaveTextContent("Read data schema");

    events = recordedParallelTools.slice(0, 3);
    await waitFor(() => expect(screen.getByTestId("agent-event-cursor")).toHaveTextContent("events #9"));
    expect(screen.getByTestId("agent-execution-trace")).toHaveTextContent("Read");
    expect(screen.getByTestId("agent-execution-trace")).toHaveTextContent("Read data schema");
    expect(screen.getByTestId("agent-execution-trace")).not.toHaveTextContent("Read node context");

    events = recordedParallelTools;
    await waitFor(() => expect(screen.getByTestId("agent-event-cursor")).toHaveTextContent("events #10"));
    expect(screen.getByTestId("agent-execution-trace")).toHaveTextContent("Working");
    expect(screen.getByTestId("agent-execution-trace")).not.toHaveTextContent("Read data schema");
    expect(mocks.sendAgentTurn).not.toHaveBeenCalled();
    expect(mocks.resumeAgentTurn).not.toHaveBeenCalled();
    expect(mocks.confirmAgentProposal).not.toHaveBeenCalled();
  });

  it("does not let another command's receipt or a usage observation clear running tool identities", async () => {
    const saved = recordedParallelTools[0].session_id;
    localStorage.setItem("workbench:agent-session:/proj:run-a:project%3Arun-a%3Anone", saved);
    mocks.getAgentSession.mockResolvedValue({ ...session(saved), status: "running" });
    mocks.getAgentEvents.mockResolvedValue({ events: [
      ...recordedParallelTools.slice(0, 2),
      { ...recordedParallelTools[2], command_id: "another-command" },
      { ...recordedParallelTools[3], event_type: "provider_step", payload: {} },
    ] });
    mount();
    await waitFor(() => expect(screen.getByTestId("agent-event-cursor")).toHaveTextContent("events #10"));
    expect(screen.getByTestId("agent-execution-trace")).toHaveTextContent(" · ");
    expect(screen.getByTestId("agent-execution-trace")).toHaveTextContent("Read node context");
    expect(screen.getByTestId("agent-execution-trace")).toHaveTextContent("Read data schema");
  });

  it("keeps old command completions from ending a reused call id in the next command", async () => {
    const start = recordedParallelTools[0];
    localStorage.setItem("workbench:agent-session:/proj:run-a:project%3Arun-a%3Anone", start.session_id);
    mocks.getAgentSession.mockResolvedValue({ ...session(start.session_id), status: "running" });
    mocks.getAgentEvents.mockResolvedValue({ events: [
      start,
      { ...start, seq: 8, event_type: "turn_start", command_id: "next-command", payload: {} },
      { ...start, seq: 9, command_id: "next-command", payload: { ...start.payload, tool_id: "inspect_result_summary" } },
      { ...recordedParallelTools[2], seq: 10 },
    ] });
    mount();
    await waitFor(() => expect(screen.getByTestId("agent-event-cursor")).toHaveTextContent("events #10"));
    expect(screen.getByTestId("agent-execution-trace")).toHaveTextContent("Read the result summary");
    expect(screen.getByTestId("agent-execution-trace")).not.toHaveTextContent("Read node context");
  });

  it.each(["turn_end", "error", "aborted"])("clears the working tool on the matching %s boundary without asserting success", async eventType => {
    const start = recordedParallelTools[0];
    localStorage.setItem("workbench:agent-session:/proj:run-a:project%3Arun-a%3Anone", start.session_id);
    mocks.getAgentSession.mockResolvedValue({ ...session(start.session_id), status: "running" });
    let events: AgentEvent[] = [start];
    mocks.getAgentEvents.mockImplementation(async () => ({ events }));
    mount();
    await waitFor(() => expect(screen.getByTestId("agent-execution-trace")).toHaveTextContent("Read node context"));
    events = [start, { ...start, seq: 8, event_type: eventType, payload: {} }];
    await waitFor(() => expect(screen.getByTestId("agent-event-cursor")).toHaveTextContent("events #8"));
    expect(screen.getByTestId("agent-execution-trace")).not.toHaveTextContent("Read node context");
    expect(screen.getByTestId("agent-execution-trace")).not.toHaveTextContent("completed");
  });

  it("clears running tool presentation when the conversation scope changes", async () => {
    const start = recordedParallelTools[0];
    localStorage.setItem("workbench:agent-session:/proj:run-a:project%3Arun-a%3Anone", start.session_id);
    localStorage.setItem("workbench:agent-session:/proj:run-b:project%3Arun-b%3Anone", "other");
    mocks.getAgentSession.mockImplementation(async (_root, id) => ({ ...session(id), status: "running" }));
    mocks.getAgentEvents.mockImplementation(async (_root, id) => ({ events: id === start.session_id ? [start] : [] }));
    const view = mount();
    await waitFor(() => expect(screen.getByTestId("agent-execution-trace")).toHaveTextContent("Read node context"));
    view.rerender(<MemoryRouter><AgentSurfaceProvider projectRoot="/proj" runId="run-b"><AgentPanel projectRoot="/proj" runId="run-b" /></AgentSurfaceProvider></MemoryRouter>);
    await waitFor(() => expect(mocks.getAgentPlan).toHaveBeenCalledWith("/proj", "other"));
    expect(screen.getByTestId("agent-execution-trace")).not.toHaveTextContent("Read node context");
    expect(mocks.sendAgentTurn).not.toHaveBeenCalled();
  });

  it("does not replace a live tool activity with a provider usage observation", async () => {
    localStorage.setItem("workbench:agent-session:/proj:run-a:project%3Arun-a%3Anone", "saved");
    mocks.getAgentSession.mockResolvedValue({ ...session("saved"), status: "running" });
    const base = { schema_version: "agent.event.v1", session_id: "saved", command_id: "command", created_at: "2026-10-20T17:00:00Z" };
    mocks.getAgentEvents.mockResolvedValue({ events: [
      { ...base, event_id: "tool", seq: 1, event_type: "tool_execution_start", payload: { tool_id: "inspect_node_context", tool_call_id: "call-1" } },
      { ...base, event_id: "usage", seq: 2, event_type: "provider_step", payload: {} },
    ] });
    mount();
    await waitFor(() => expect(screen.getByTestId("agent-event-cursor")).toHaveTextContent("events #2"));
    expect(screen.getByTestId("agent-execution-trace")).toHaveTextContent("Read");
  });

  it("sends the selected mode and explicitly queues follow-ups without starting a second turn", async () => {
    mocks.sendAgentTurn.mockReturnValue(new Promise(() => {}));
    mocks.queueAgentTurnMessage.mockResolvedValue({status:"queued"});
    mount();
    fireEvent.change(screen.getByRole("combobox", {name:"Agent execution mode"}), {target:{value:"auto"}});
    fireEvent.change(screen.getByRole("textbox", {name:"Ask Agent"}), {target:{value:"First request"}});
    fireEvent.click(screen.getByRole("button", {name:"Send to Agent"}));
    await waitFor(() => expect(mocks.sendAgentTurn).toHaveBeenCalledWith("/proj","agent_chain_new","First request",expect.any(AbortSignal),undefined,"auto_read_only","auto"));
    fireEvent.change(screen.getByRole("textbox", {name:"Ask Agent"}), {target:{value:"Next request"}});
    fireEvent.keyDown(screen.getByRole("textbox", {name:"Ask Agent"}), {key:"Enter"});
    expect(mocks.sendAgentTurn).toHaveBeenCalledTimes(1);
    fireEvent.change(screen.getByRole("combobox", {name:"Active-turn message delivery"}), {target:{value:"follow_up"}});
    fireEvent.click(screen.getByRole("button", {name:"Send active-turn message"}));
    await waitFor(() => expect(mocks.queueAgentTurnMessage).toHaveBeenCalledWith("/proj","agent_chain_new","follow_up","Next request"));
    await waitFor(() => expect(screen.getByRole("textbox", {name:"Ask Agent"})).toHaveValue(""));
  });

  it("restores Auto with its read-only policy in the same next-turn request", async () => {
    localStorage.setItem("workbench:agent-session:/proj:run-a:project%3Arun-a%3Anone", "saved");
    mocks.getAgentSession.mockResolvedValue({ ...session("saved"), execution_mode: "auto" });
    mount();
    await waitFor(() => expect(screen.getByRole("combobox", {name:"Agent execution mode"})).toHaveValue("auto"));
    expect(mocks.sendAgentTurn).not.toHaveBeenCalled();
    fireEvent.change(screen.getByRole("textbox", {name:"Ask Agent"}), {target:{value:"Continue the plan"}});
    fireEvent.click(screen.getByRole("button", {name:"Send to Agent"}));
    await waitFor(() => expect(mocks.sendAgentTurn).toHaveBeenCalledWith("/proj", "saved", "Continue the plan", expect.any(AbortSignal), undefined, "auto_read_only", "auto"));
  });

  it("an explicit Review selection replaces Auto and a refused turn is shown as a failure", async () => {
    function ReviewControl() {
      const agent = useAgentSurface();
      return <button onClick={() => agent.setExecutionPolicy?.("proposal_only")}>Review next turn</button>;
    }
    mocks.sendAgentTurn.mockRejectedValue(new Error("Turn was refused"));
    render(<MemoryRouter><AgentSurfaceProvider projectRoot="/proj" runId="run-a">
      <ReviewControl /><AgentPanel projectRoot="/proj" runId="run-a" />
    </AgentSurfaceProvider></MemoryRouter>);
    fireEvent.change(screen.getByRole("combobox", {name:"Agent execution mode"}), {target:{value:"auto"}});
    fireEvent.click(screen.getByRole("button", {name:"Review next turn"}));
    expect(screen.getByRole("combobox", {name:"Agent execution mode"})).toHaveValue("ask");
    fireEvent.change(screen.getByRole("textbox", {name:"Ask Agent"}), {target:{value:"Review this operation"}});
    fireEvent.click(screen.getByRole("button", {name:"Send to Agent"}));
    await waitFor(() => expect(mocks.sendAgentTurn).toHaveBeenCalledWith("/proj", "agent_chain_new", "Review this operation", expect.any(AbortSignal), undefined, "proposal_only", "ask"));
    expect(await screen.findByText("Turn was refused")).toBeInTheDocument();
    expect(screen.queryByTestId("agent-message-assistant")).not.toBeInTheDocument();
    expect(mocks.continueAgentTurn).not.toHaveBeenCalled();
  });

  it("keeps a read-only selection after an Ask-mode continuation returns", async () => {
    function ReadOnlyControl() {
      const agent = useAgentSurface();
      return <><output data-testid="execution-policy">{agent.executionPolicy}</output>
        <button onClick={() => agent.setExecutionPolicy?.("auto_read_only")}>Select read-only</button>
        <button onClick={() => void agent.continueTurn?.()}>Continue read-only</button></>;
    }
    localStorage.setItem("workbench:agent-session:/proj:run-a:project%3Arun-a%3Anone", "saved");
    mocks.getAgentSession.mockResolvedValue({ ...session("saved"), execution_mode: "ask" });
    mocks.continueAgentTurn.mockResolvedValue({ session: { ...session("saved"), execution_mode: "ask" }, status: "idle" });
    render(<MemoryRouter><AgentSurfaceProvider projectRoot="/proj" runId="run-a">
      <ReadOnlyControl /><AgentPanel projectRoot="/proj" runId="run-a" />
    </AgentSurfaceProvider></MemoryRouter>);
    await waitFor(() => expect(mocks.getAgentSession).toHaveBeenCalledWith("/proj", "saved"));
    fireEvent.click(screen.getByRole("button", {name:"Select read-only"}));
    fireEvent.click(screen.getByRole("button", {name:"Continue read-only"}));
    await waitFor(() => expect(mocks.continueAgentTurn).toHaveBeenCalledWith("/proj", "saved", expect.objectContaining({execution_mode:"ask", execution_policy:"auto_read_only"}), expect.any(AbortSignal)));
    await waitFor(() => expect(screen.queryByRole("button", {name:"Stop Agent"})).not.toBeInTheDocument());
    expect(screen.getByTestId("execution-policy")).toHaveTextContent("auto_read_only");
  });

  it("loads recovery state without running a model, then resumes only the original turn on click", async () => {
    mocks.getAgentSession.mockResolvedValue(session("saved"));
    mocks.getAgentTurnState.mockResolvedValue({turns:[{turn_id:"original",status:"interrupted",requires_reconcile:true}]});
    mocks.resumeAgentTurn.mockResolvedValue({session:session("saved"),status:"idle"});
    render(<MemoryRouter initialEntries={["/?agent_session=saved"]}><AgentSurfaceProvider projectRoot="/proj" runId="run-a"><AgentPanel projectRoot="/proj" runId="run-a" /></AgentSurfaceProvider></MemoryRouter>);
    const resume=await screen.findByRole("button",{name:"Resume original turn"});
    expect(mocks.resumeAgentTurn).not.toHaveBeenCalled();
    fireEvent.change(screen.getByRole("textbox",{name:"Ask Agent"}),{target:{value:"Do not replace command"}});
    fireEvent.click(screen.getByRole("button",{name:"Send to Agent"}));
    expect(mocks.sendAgentTurn).not.toHaveBeenCalled();
    fireEvent.click(resume);
    await waitFor(() => expect(mocks.resumeAgentTurn).toHaveBeenCalledWith("/proj","saved","original",expect.any(AbortSignal)));
    expect(mocks.continueAgentTurn).not.toHaveBeenCalled();
  });

  it.each([
    ["panel", "running"], ["column", "running"],
    ["panel", "working"], ["column", "working"],
    ["panel", "cancelling"], ["column", "cancelling"],
  ] as const)("does not offer recovery while the restored %s turn is still %s", async (surface, status) => {
    mocks.getAgentSession.mockResolvedValue({ ...session("saved"), status });
    mocks.getAgentTurnState.mockResolvedValue({ turns: [{ turn_id: "original", status: "running", requires_reconcile: false }] });
    function DurableState() {
      const agent = useAgentSurface();
      return <span data-testid="durable-state">{agent.durableTurns?.[0]?.status}</span>;
    }
    render(<MemoryRouter initialEntries={["/?agent_session=saved"]}><AgentSurfaceProvider projectRoot="/proj" runId="run-a">
      <AgentPanel projectRoot="/proj" runId="run-a" compactHeader={surface === "column"} composer={surface === "column" ? <AgentColumnComposer /> : undefined} />
      <DurableState />
    </AgentSurfaceProvider></MemoryRouter>);
    await waitFor(() => expect(screen.getByTestId("durable-state")).toHaveTextContent("running"));
    expect(screen.getByRole("button", { name: "Stop Agent" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: /^Resume/ })).not.toBeInTheDocument();
    expect(screen.queryByText(/Previous turn unfinished|Unfinished turn:/)).not.toBeInTheDocument();
    expect(mocks.resumeAgentTurn).not.toHaveBeenCalled();
    expect(mocks.continueAgentTurn).not.toHaveBeenCalled();
    expect(mocks.sendAgentTurn).not.toHaveBeenCalled();
  });

  it.each(["panel", "column"] as const)("shows a restored interrupted turn instead of stale running progress in the %s", async surface => {
    let finishStalePoll!: (value: ReturnType<typeof session>) => void;
    const staleSession = { ...session("saved"), status: "running" };
    mocks.getAgentSession.mockResolvedValueOnce(staleSession).mockReturnValue(new Promise(resolve => { finishStalePoll = resolve; }));
    mocks.getAgentEvents.mockResolvedValue({ events: [
      { seq: 1, event_type: "message_update", payload: { delta: "An interrupted draft" } },
      { seq: 2, event_type: "tool_execution_end", payload: { entry_id: "recorded-tool" } },
    ] });
    mocks.getAgentTurnState.mockResolvedValue({ turns: [{ turn_id: "original", status: "interrupted", requires_reconcile: true }] });
    render(<MemoryRouter initialEntries={["/?agent_session=saved"]}><AgentSurfaceProvider projectRoot="/proj" runId="run-a">
      <AgentPanel projectRoot="/proj" runId="run-a" compactHeader={surface === "column"} composer={surface === "column" ? <AgentColumnComposer /> : undefined} />
    </AgentSurfaceProvider></MemoryRouter>);

    await screen.findByRole("button", { name: surface === "column" ? "Resume" : "Resume original turn" });
    expect(screen.queryAllByRole("button", { name: "Stop Agent" })).toHaveLength(0);
    expect(screen.queryByLabelText("Agent execution progress")).not.toBeInTheDocument();
    expect(screen.queryByTestId("agent-turn-progress")).not.toBeInTheDocument();
    await act(async () => { finishStalePoll(staleSession); });
    expect(screen.queryByRole("button", { name: "Stop Agent" })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Agent execution progress")).not.toBeInTheDocument();

    fireEvent.change(screen.getByRole("textbox", { name: "Ask Agent" }), { target: { value: "Do not replace the interrupted request" } });
    fireEvent.click(screen.getByRole("button", { name: "Send to Agent" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("An unfinished turn needs recovery.");
    expect(mocks.sendAgentTurn).not.toHaveBeenCalled();
    expect(mocks.continueAgentTurn).not.toHaveBeenCalled();
    expect(mocks.resumeAgentTurn).not.toHaveBeenCalled();
    mocks.resumeAgentTurn.mockReturnValue(new Promise(() => {}));
    fireEvent.click(screen.getByRole("button", { name: surface === "column" ? "Resume" : "Resume original turn" }));
    await waitFor(() => expect(mocks.resumeAgentTurn).toHaveBeenCalledWith("/proj", "saved", "original", expect.any(AbortSignal)));
    expect(screen.getByRole("button", { name: "Stop Agent" })).toBeInTheDocument();
    expect(screen.getByLabelText("Agent execution progress")).toBeInTheDocument();
  });

  it.each([false, true])("hydrates recorded tool output during the local request without overwriting a later reply (late read: %s)", async lateRead => {
    let finishTurn!: (result: unknown) => void;
    let finishRead!: (result: ReturnType<typeof session>) => void;
    const question = agentMessageFixture({ entry_id: "u1", role: "user", content: "Check the evidence" });
    const recordedTool = agentMessageFixture({ entry_id: "t1", role: "tool", name: "inspect_model_result", content: JSON.stringify({ ok: true, output: { raw: "LARGE_RAW_OUTPUT" } }) });
    const progress = { ...session("agent_chain_new", [question, recordedTool]), status: "running" };
    mocks.getAgentEvents.mockImplementation(async () => ({ events: mocks.sendAgentTurn.mock.calls.length ? [{ seq: 1, event_type: "tool_execution_end", payload: { tool_id: "inspect_model_result", entry_id: "t1", ok: true } }] : [] }));
    mocks.getAgentSession.mockImplementation(() => lateRead ? new Promise(resolve => { finishRead = resolve; }) : Promise.resolve(progress));
    mocks.sendAgentTurn.mockReturnValue(new Promise(resolve => { finishTurn = resolve; }));
    mount();
    fireEvent.change(screen.getByRole("textbox", { name: "Ask Agent" }), { target: { value: "Check the evidence" } });
    fireEvent.click(screen.getByRole("button", { name: "Send to Agent" }));
    await waitFor(() => expect(mocks.getAgentSession).toHaveBeenCalledWith("/proj", "agent_chain_new"));
    if (!lateRead) {
      expect(await screen.findByTestId("agent-message-tool")).toHaveTextContent("Read model result");
      expect(screen.getByTestId("agent-reasoning-u1")).toHaveAttribute("open");
      expect(screen.getByRole("button", { name: "Stop Agent" })).toBeInTheDocument();
      expect(screen.getByTestId("agent-message-tool")).not.toHaveTextContent("LARGE_RAW_OUTPUT");
    }
    const completed = session("agent_chain_new", [question, recordedTool, agentMessageFixture({ entry_id: "a1", role: "assistant", content: "Evidence checked.", stop_reason: "stop" })]);
    await act(async () => { finishTurn({ session: completed, status: "idle" }); });
    if (lateRead) await act(async () => { finishRead(progress); });
    expect(await screen.findByText("Evidence checked.")).toBeInTheDocument();
    expect(mocks.sendAgentTurn).toHaveBeenCalledTimes(1);
    expect(mocks.continueAgentTurn).not.toHaveBeenCalled();
    expect(mocks.resumeAgentTurn).not.toHaveBeenCalled();
  });

  it.each([
    ["awaiting_approval", "completed"], ["idle", "failed"], ["awaiting_approval", "interrupted"],
  ])("tails a %s session for external progress and %s without repeatedly downloading its history", async (initialStatus, finalStatus) => {
    let saved = { ...session("saved", [agentMessageFixture({ entry_id: "u1", role: "user", content: "First request" })]), status: initialStatus };
    let events: Array<{ seq: number; event_type: string; payload: Record<string, unknown> }> = [];
    mocks.getAgentSession.mockImplementation(async () => saved);
    mocks.getAgentEvents.mockImplementation(async () => ({ events }));
    const Status = () => <output data-testid="external-session-status">{useAgentSurface().sessionStatus}</output>;
    render(<MemoryRouter initialEntries={["/?agent_session=saved"]}><AgentSurfaceProvider projectRoot="/proj" runId="run-a">
      <AgentPanel projectRoot="/proj" runId="run-a" /><Status />
    </AgentSurfaceProvider></MemoryRouter>);
    await waitFor(() => expect(screen.getByTestId("external-session-status")).toHaveTextContent(initialStatus));
    const initialTails = mocks.getAgentEvents.mock.calls.length;
    await waitFor(() => expect(mocks.getAgentEvents.mock.calls.length).toBeGreaterThan(initialTails), { timeout: 1500 });
    expect(mocks.getAgentSession).toHaveBeenCalledTimes(1);

    saved = { ...saved, status: finalStatus, messages: [...saved.messages,
      agentMessageFixture({ entry_id: "t-external", role: "tool", name: "inspect_result", content: JSON.stringify({ ok: false, error: "artifact_unavailable" }) }),
      agentMessageFixture({ entry_id: "a-external", role: "assistant", content: "External terminal reply", stop_reason: finalStatus === "failed" ? "error" : "stop" }),
    ] };
    events = [{ seq: 1, event_type: "tool_execution_end", payload: { entry_id: "t-external" } },
      { seq: 2, event_type: "message_end", payload: { entry_id: "a-external" } },
      { seq: 3, event_type: "agent_end", payload: { stop_reason: finalStatus } }];
    expect(await screen.findByText("External terminal reply", {}, { timeout: 1500 })).toBeInTheDocument();
    expect(screen.getByTestId("agent-message-tool")).toHaveTextContent("artifact_unavailable");
    expect(screen.getByTestId("external-session-status")).toHaveTextContent(finalStatus);
    expect(screen.queryByRole("button", { name: "Stop Agent" })).not.toBeInTheDocument();
    const settledTails = mocks.getAgentEvents.mock.calls.length;
    await waitFor(() => expect(mocks.getAgentEvents.mock.calls.length).toBeGreaterThan(settledTails), { timeout: 1500 });
    expect(mocks.getAgentSession).toHaveBeenCalledTimes(2);
    expect(mocks.sendAgentTurn).not.toHaveBeenCalled();
    expect(mocks.continueAgentTurn).not.toHaveBeenCalled();
    expect(mocks.resumeAgentTurn).not.toHaveBeenCalled();
  });

  it("ignores an external refresh arriving after switching session scope", async () => {
    let added = false;
    let finishRead!: (result: ReturnType<typeof session>) => void;
    mocks.getAgentSession.mockResolvedValueOnce({ ...session("saved"), status: "awaiting_approval" })
      .mockReturnValue(new Promise(resolve => { finishRead = resolve; }));
    mocks.getAgentEvents.mockImplementation(async () => ({ events: added ? [{ seq: 1, event_type: "message_end", payload: {} }] : [] }));
    const tree = () => <MemoryRouter initialEntries={["/?agent_session=saved"]}><AgentSurfaceProvider projectRoot="/proj" runId="run-a"><AgentPanel projectRoot="/proj" runId="run-a" /></AgentSurfaceProvider></MemoryRouter>;
    const view = render(tree());
    await waitFor(() => expect(mocks.getAgentSession).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(mocks.getAgentEvents.mock.calls.length).toBeGreaterThanOrEqual(2));
    added = true;
    await waitFor(() => expect(mocks.getAgentSession).toHaveBeenCalledTimes(2), { timeout: 1500 });
    mocks.workbenchState.agentFocus = { kind: "report", id: "other-scope", runId: "run-a" };
    view.rerender(tree());
    await act(async () => { finishRead(session("saved", [agentMessageFixture({ entry_id: "late", role: "assistant", content: "Stale external reply" })])); });
    expect(screen.queryByText("Stale external reply")).not.toBeInTheDocument();
    expect(mocks.sendAgentTurn).not.toHaveBeenCalled();
  });

  it("loads the session plan and approves its exact visible version without continuing", async () => {
    const plan={plan_id:"p",version:4,status:"draft",question:"Server-owned analysis question",criteria:["Report uncertainty"],
      steps:[{step_id:"a",title:"Inspect evidence",status:"pending",operation_ids:["stat.describe"],depends_on:[],expected_outputs:[],added_after_results:false}],approved_version:null};
    mocks.getAgentSession.mockResolvedValue(session("saved"));
    mocks.getAgentPlan.mockResolvedValue({plan,versions:[{version:4,status:"draft",updated_at:"today"}]});
    mocks.approveAgentPlan.mockResolvedValue({plan:{...plan,status:"approved",approved_version:4}});
    render(<MemoryRouter initialEntries={["/?agent_session=saved"]}><AgentSurfaceProvider projectRoot="/proj" runId="run-a"><AgentPanel projectRoot="/proj" runId="run-a" /></AgentSurfaceProvider></MemoryRouter>);
    await screen.findByText("Server-owned analysis question");
    fireEvent.click(screen.getByRole("button",{name:"Approve plan v4"}));
    await waitFor(() => expect(mocks.approveAgentPlan).toHaveBeenCalledWith("/proj","saved",4));
    expect(mocks.continueAgentTurn).not.toHaveBeenCalled();
    expect(mocks.sendAgentTurn).not.toHaveBeenCalled();
  });

  it("checks registered deliverables on demand without a Provider request", async () => {
    const plan={plan_id:"p",version:4,status:"draft",question:"Verify this analysis",criteria:["Report uncertainty"],steps:[],approved_version:null};
    mocks.getAgentSession.mockResolvedValue(session("saved"));
    mocks.getAgentPlan.mockResolvedValue({plan,versions:[]});
    mocks.getAgentPlanVerification.mockResolvedValue({plan_id:"p",plan_version:4,status:"partial",playbook_status:"requirements_met",
      criteria_verification:{plan_id:"p",plan_version:4,basis_sha256:"a".repeat(64),status:"partial",requirements:[],unbound_slots:[{criterion_index:0}]}});
    render(<MemoryRouter initialEntries={["/?agent_session=saved"]}><AgentSurfaceProvider projectRoot="/proj" runId="run-a"><AgentPanel projectRoot="/proj" runId="run-a" /></AgentSurfaceProvider></MemoryRouter>);
    await screen.findByText("Verify this analysis");
    expect(mocks.getAgentPlanVerification).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button",{name:"Check deliverables"}));
    await screen.findByText(/Not bound: Report uncertainty/);
    expect(mocks.getAgentPlanVerification).toHaveBeenCalledWith("/proj","saved");
    expect(mocks.sendAgentTurn).not.toHaveBeenCalled();
    expect(mocks.continueAgentTurn).not.toHaveBeenCalled();
  });

  it("does not show a late verification as evidence for a revised plan", async () => {
    const plan={plan_id:"p",version:4,status:"draft",question:"Verification before revision",criteria:[],steps:[],approved_version:null};
    let finish!: (value: unknown) => void;
    mocks.getAgentSession.mockResolvedValue(session("saved"));
    mocks.getAgentPlan.mockResolvedValue({plan,versions:[]});
    mocks.getAgentPlanVerification.mockReturnValue(new Promise(resolve => {finish=resolve;}));
    render(<MemoryRouter initialEntries={["/?agent_session=saved"]}><AgentSurfaceProvider projectRoot="/proj" runId="run-a"><AgentPanel projectRoot="/proj" runId="run-a" /></AgentSurfaceProvider></MemoryRouter>);
    await screen.findByText("Verification before revision");
    fireEvent.click(screen.getByRole("button",{name:"Check deliverables"}));
    await waitFor(() => expect(mocks.getAgentPlanVerification).toHaveBeenCalledTimes(1));
    mocks.getAgentPlan.mockResolvedValue({plan:{...plan,version:5,question:"Revised analysis"},versions:[]});
    fireEvent.click(screen.getByRole("button",{name:"Reload current plan"}));
    await screen.findByText("Revised analysis");
    await act(async () => {finish({plan_id:"p",plan_version:4,status:"requirements_met",playbook_status:"requirements_met",
      criteria_verification:{plan_id:"p",plan_version:4,basis_sha256:"a".repeat(64),status:"requirements_met",requirements:[],unbound_slots:[]}});});
    expect(screen.getByText("Not checked for this plan version.")).toBeInTheDocument();
    expect(screen.queryByText("Delivery requirements met")).not.toBeInTheDocument();
    expect(mocks.sendAgentTurn).not.toHaveBeenCalled();
  });

  it("releases a pending verification when forking and ignores its late result", async () => {
    const plan={plan_id:"p",version:4,status:"draft",question:"Original plan",criteria:[],steps:[],approved_version:null};
    let finish!: (value: unknown) => void;
    mocks.getAgentSession.mockResolvedValue(session("saved"));
    mocks.getAgentPlan.mockImplementation(async (_root: string, id: string) => ({plan:{...plan,question:id === "saved" ? "Original plan" : "Forked plan"},versions:[]}));
    mocks.getAgentPlanVerification.mockReturnValue(new Promise(resolve => {finish=resolve;}));
    mocks.forkAgentSession.mockResolvedValue({session:session("forked")});
    function ForkControl() {
      const agent = useAgentSurface();
      return <button onClick={() => void agent.forkConversation?.("entry")}>Fork test conversation</button>;
    }
    render(<MemoryRouter initialEntries={["/?agent_session=saved"]}><AgentSurfaceProvider projectRoot="/proj" runId="run-a"><AgentPanel projectRoot="/proj" runId="run-a" /><ForkControl /></AgentSurfaceProvider></MemoryRouter>);
    await screen.findByText("Original plan");
    fireEvent.click(screen.getByRole("button",{name:"Check deliverables"}));
    await waitFor(() => expect(mocks.getAgentPlanVerification).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByRole("button",{name:"Fork test conversation"}));
    await screen.findByText("Forked plan");
    expect(screen.getByRole("button",{name:"Check deliverables"})).toBeEnabled();
    await act(async () => {finish({plan_id:"p",plan_version:4,status:"requirements_met",playbook_status:"requirements_met",
      criteria_verification:{plan_id:"p",plan_version:4,basis_sha256:"a".repeat(64),status:"requirements_met",requirements:[],unbound_slots:[]}});});
    expect(screen.queryByText("Delivery requirements met")).not.toBeInTheDocument();
    expect(mocks.sendAgentTurn).not.toHaveBeenCalled();
  });

  it.each(["success","rejected","changed"] as const)("Auto approve-and-run continues only an unchanged approved version: %s", async outcome => {
    const original={plan_id:"p",version:4,status:"draft",question:"Auto analysis",criteria:["Report uncertainty"],steps:[],approved_version:null};
    const approved={...original,status:"approved",approved_version:4};
    let current=original as typeof original | typeof approved;
    mocks.getAgentSession.mockResolvedValue({...session("saved"),execution_mode:"auto"});
    mocks.getAgentPlan.mockImplementation(async () => ({plan:current,versions:[]}));
    mocks.approveAgentPlan.mockImplementation(async () => {
      if (outcome === "rejected") throw new Error("Approval version conflict");
      current=outcome === "changed" ? {...original,version:5} : approved;
      return {plan:approved};
    });
    mocks.continueAgentTurn.mockResolvedValue({session:session("saved"),status:"idle"});
    render(<MemoryRouter initialEntries={["/?agent_session=saved"]}><AgentSurfaceProvider projectRoot="/proj" runId="run-a"><AgentPanel projectRoot="/proj" runId="run-a" /></AgentSurfaceProvider></MemoryRouter>);
    fireEvent.click(await screen.findByRole("button",{name:"Approve and run plan v4"}));
    await waitFor(() => expect(mocks.approveAgentPlan).toHaveBeenCalledWith("/proj","saved",4));
    if (outcome === "success") await waitFor(() => expect(mocks.continueAgentTurn).toHaveBeenCalledWith("/proj","saved",expect.objectContaining({execution_mode:"auto"}),expect.any(AbortSignal)));
    else {
      if (outcome === "rejected") await screen.findByText(/Approval version conflict/);
      else await screen.findByRole("button",{name:"Approve plan v5"});
      expect(mocks.continueAgentTurn).not.toHaveBeenCalled();
    }
    expect(mocks.sendAgentTurn).not.toHaveBeenCalled();
  });

  it("does not continue after switching session scope during Auto approval", async () => {
    const plan={plan_id:"p",version:4,status:"draft",question:"Auto approval in session A",criteria:[],steps:[],approved_version:null};
    let finishApproval!: (value: unknown) => void;
    mocks.getAgentSession.mockResolvedValue({...session("saved"),execution_mode:"auto"});
    mocks.getAgentPlan.mockResolvedValue({plan,versions:[]});
    mocks.approveAgentPlan.mockReturnValue(new Promise(resolve => {finishApproval=resolve;}));
    const tree=() => <MemoryRouter initialEntries={["/?agent_session=saved"]}><AgentSurfaceProvider projectRoot="/proj" runId="run-a"><AgentPanel projectRoot="/proj" runId="run-a" /></AgentSurfaceProvider></MemoryRouter>;
    const view=render(tree());
    fireEvent.click(await screen.findByRole("button",{name:"Approve and run plan v4"}));
    await waitFor(() => expect(mocks.approveAgentPlan).toHaveBeenCalledTimes(1));
    mocks.workbenchState.agentFocus={kind:"report",id:"different-focus",runId:"run-a"};
    view.rerender(tree());
    await waitFor(() => expect(screen.queryByText("Auto approval in session A")).not.toBeInTheDocument());
    await act(async () => {finishApproval({plan:{...plan,status:"approved",approved_version:4}});});
    expect(mocks.continueAgentTurn).not.toHaveBeenCalled();
    expect(mocks.sendAgentTurn).not.toHaveBeenCalled();
  });

  it("blocks approve-and-run for a known active owner", async () => {
    const plan={plan_id:"p",version:4,status:"draft",question:"Active plan",criteria:[],steps:[],approved_version:null};
    mocks.getAgentSession.mockResolvedValue({...session("saved"),execution_mode:"auto",status:"running"});
    mocks.getAgentPlan.mockResolvedValue({plan,versions:[]});
    mocks.getAgentTurnState.mockResolvedValue({turns:[{turn_id:"active",status:"running",requires_reconcile:false}]});
    render(<MemoryRouter initialEntries={["/?agent_session=saved"]}><AgentSurfaceProvider projectRoot="/proj" runId="run-a"><AgentPanel projectRoot="/proj" runId="run-a" /></AgentSurfaceProvider></MemoryRouter>);
    const button=await screen.findByRole("button",{name:"Approve and run plan v4"});
    expect(button).toBeDisabled();
    fireEvent.click(button);
    expect(mocks.approveAgentPlan).not.toHaveBeenCalled();
    expect(mocks.continueAgentTurn).not.toHaveBeenCalled();
  });

  it("restores the saved Ask/Auto mode without executing a turn", async () => {
    mocks.getAgentSession.mockResolvedValue({...session("saved"),execution_mode:"auto"});
    render(<MemoryRouter initialEntries={["/?agent_session=saved"]}><AgentSurfaceProvider projectRoot="/proj" runId="run-a"><AgentPanel projectRoot="/proj" runId="run-a" /></AgentSurfaceProvider></MemoryRouter>);
    await waitFor(() => expect(screen.getByRole("combobox",{name:"Agent execution mode"})).toHaveValue("auto"));
    expect(mocks.sendAgentTurn).not.toHaveBeenCalled();
    expect(mocks.continueAgentTurn).not.toHaveBeenCalled();
  });

  it.each([false,true])("explicitly resumes an idle orphan and prevents a concurrent Resume (server rejects: %s)", async rejects => {
    mocks.getAgentSession.mockResolvedValue({...session("saved"),status:"idle"});
    mocks.getAgentTurnState.mockResolvedValue({turns:[{turn_id:"orphan",status:"running",requires_reconcile:false}]});
    let finishResume!: () => void;
    mocks.resumeAgentTurn.mockImplementation(() => new Promise((resolve, reject) => {
      finishResume = () => rejects ? reject(new Error("The server still has an active owner."))
        : resolve({session:session("saved"),status:"idle"});
    }));
    render(<MemoryRouter initialEntries={["/?agent_session=saved"]}><AgentSurfaceProvider projectRoot="/proj" runId="run-a"><AgentPanel projectRoot="/proj" runId="run-a" /></AgentSurfaceProvider></MemoryRouter>);
    const resume=await screen.findByRole("button",{name:"Resume original turn"});
    expect(mocks.resumeAgentTurn).not.toHaveBeenCalled();
    expect(screen.queryByRole("button",{name:"Continue Agent"})).not.toBeInTheDocument();
    fireEvent.change(screen.getByRole("textbox",{name:"Ask Agent"}),{target:{value:"Do not start a replacement"}});
    fireEvent.keyDown(screen.getByRole("textbox",{name:"Ask Agent"}),{key:"Enter"});
    expect(mocks.sendAgentTurn).not.toHaveBeenCalled();
    fireEvent.click(resume);
    await waitFor(() => expect(mocks.resumeAgentTurn).toHaveBeenCalledWith("/proj","saved","orphan",expect.any(AbortSignal)));
    expect(screen.queryByRole("button",{name:"Resume original turn"})).not.toBeInTheDocument();
    expect(screen.getByRole("button",{name:"Stop Agent"})).toBeInTheDocument();
    expect(mocks.resumeAgentTurn).toHaveBeenCalledTimes(1);
    expect(mocks.continueAgentTurn).not.toHaveBeenCalled();
    await act(async () => finishResume());
    if (rejects) expect(await screen.findByRole("alert")).toHaveTextContent("The server still has an active owner.");
  });

  it("does not offer ordinary send for a restored running session", async () => {
    mocks.getAgentSession.mockResolvedValue({...session("saved"),status:"running"});
    render(<MemoryRouter initialEntries={["/?agent_session=saved"]}><AgentSurfaceProvider projectRoot="/proj" runId="run-a"><AgentPanel projectRoot="/proj" runId="run-a" /></AgentSurfaceProvider></MemoryRouter>);
    await screen.findByRole("button",{name:"Stop Agent"});
    fireEvent.change(screen.getByRole("textbox",{name:"Ask Agent"}),{target:{value:"Direction"}});
    fireEvent.keyDown(screen.getByRole("textbox",{name:"Ask Agent"}),{key:"Enter"});
    expect(mocks.sendAgentTurn).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button",{name:"Stop Agent"}));
    await waitFor(() => expect(mocks.abortAgentTurn).toHaveBeenCalledWith("/proj","saved"));
  });

  it.each(["report", "plan"] as const)("creates an authoritative %s focus without reusing graph sessions", async kind => {
    sessionStorage.setItem("workbench:agent-session:/proj:run-a:project%3Arun-a%3Anone", "old_graph_session");
    mocks.workbenchState.agentFocus = { kind, id: kind === "report" ? "run-a" : "notebook-a", runId: "run-a" };
    render(<MemoryRouter initialEntries={["/?agent_session=old_graph_session"]}><AgentSurfaceProvider projectRoot="/proj" runId="run-a"><AgentPanel projectRoot="/proj" runId="run-a" /></AgentSurfaceProvider></MemoryRouter>);
    await screen.findByRole("listbox", { name: "Agent model" });
    fireEvent.change(screen.getByRole("textbox", { name: "Ask Agent" }), { target: { value: "Inspect current focus" } });
    fireEvent.click(screen.getByRole("button", { name: "Send to Agent" }));
    await waitFor(() => expect(mocks.createAgentSession).toHaveBeenCalledWith("/proj", expect.objectContaining({ focus: expect.objectContaining({kind, id: kind === "report" ? "run-a" : "notebook-a", label: expect.stringMatching(kind === "report" ? /^Report/ : /^Plan/)}) })));
    expect(mocks.getAgentSession).not.toHaveBeenCalledWith("/proj", "old_graph_session");
  });

  it("keeps an unsent message when the view, and with it the Agent's scope, changes", async () => {
    mocks.workbenchState.agentFocus = null;
    const tree = () => <MemoryRouter><AgentSurfaceProvider projectRoot="/proj" runId="run-a"><AgentPanel projectRoot="/proj" runId="run-a" /></AgentSurfaceProvider></MemoryRouter>;
    const view = render(tree());
    await screen.findByRole("listbox", { name: "Agent model" });
    fireEvent.change(screen.getByRole("textbox", { name: "Ask Agent" }), { target: { value: "Half-written question" } });
    mocks.workbenchState.agentFocus = { kind: "report", id: "run-a", runId: "run-a" };
    view.rerender(tree());
    await waitFor(() => expect(screen.getByRole("textbox", { name: "Ask Agent" })).toHaveValue("Half-written question"));
    view.unmount();
    render(tree());
    expect(await screen.findByRole("textbox", { name: "Ask Agent" })).toHaveValue("Half-written question");
    sessionStorage.removeItem("workbench:agent-draft:/proj");
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

  it("creates a project-scoped Main Agent when no graph node is selected", async () => {
    mocks.forest.current = {
      forest: {
        schemaVersion: 4,
        legacy: false,
        nodes: [{
          nodeKey: "run-a::model:ols_1",
          nodeHash: "node-hash-a",
          opNodeId: "model:ols_1",
          kind: "model",
          stage: "model",
          title: "OLS",
          summary: "Treatment effect",
          runs: ["run-a"],
        }],
        edges: [],
        heads: [{
          runId: "run-a",
          headNodeHash: "node-hash-a",
          fromNode: null,
          rerunOf: null,
          rerunReason: null,
          status: "completed",
          createdAt: "2026-07-18T00:00:00Z",
        }],
        familyCount: 1,
        familyRunCount: 1,
      },
      activeRunId: "run-a",
      setActiveRunId: vi.fn(),
    };

    mount();
    fireEvent.change(await screen.findByRole("textbox", { name: "Ask Agent" }), {
      target: { value: "总结整个项目的分析链。" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send to Agent" }));

    await waitFor(() => expect(mocks.createAgentSession).toHaveBeenCalledWith(
      "/proj",
      expect.objectContaining({
        role: "main",
        chain_id: "project:/proj",
        run_id: undefined,
        context_packet: expect.objectContaining({
          scope: "global_project",
          project_overview: expect.objectContaining({ family_count: 1, run_count: 1 }),
        }),
      }),
    ));
  });

  it("clears the composer and shows the user turn immediately while the Agent is pending", async () => {
    let releaseCreate!: (value: ReturnType<typeof session>) => void;
    mocks.createAgentSession.mockReturnValueOnce(new Promise((resolve) => {
      releaseCreate = resolve;
    }));
    mount();

    const input = await screen.findByRole("textbox", { name: "Ask Agent" });
    fireEvent.change(input, { target: { value: "先检查这个图" } });
    fireEvent.click(screen.getByRole("button", { name: "Send to Agent" }));

    expect(input).toHaveValue("");
    expect(screen.getByText("先检查这个图")).toBeInTheDocument();

    releaseCreate(session("agent_chain_new"));
    await waitFor(() => expect(mocks.sendAgentTurn).toHaveBeenCalledWith(
      "/proj",
      "agent_chain_new",
      "先检查这个图",
      expect.any(AbortSignal),
      undefined, // a chain session's context is bound by the server, not refreshed per turn
      "proposal_only",
      "ask",
    ));
  });

  it("renders public assistant deltas while a turn is still running", async () => {
    let resolveTurn!: (value: {
      session: ReturnType<typeof session>;
      assistant: AgentMessage;
      status: string;
    }) => void;
    mocks.sendAgentTurn.mockReturnValueOnce(new Promise((resolve) => {
      resolveTurn = resolve;
    }));
    mocks.getAgentEvents.mockResolvedValue({
      events: [{
        event_id: "event-live-delta",
        session_id: "agent_chain_new",
        seq: 1,
        event_type: "message_update",
        payload: { delta: "正在核对当前模型的公开结果。" },
        command_id: "command-1",
        created_at: "2026-07-30T14:30:00Z",
      }],
    });
    mount();

    fireEvent.change(await screen.findByRole("textbox", { name: "Ask Agent" }), {
      target: { value: "解释当前模型" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send to Agent" }));

    expect(await screen.findByTestId("agent-live-response")).toHaveTextContent(
      "正在核对当前模型的公开结果。",
    );

    await act(async () => {
      resolveTurn({
        session: session("agent_chain_new", [
          agentMessageFixture({ entry_id: "u1", role: "user", content: "解释当前模型" }),
          agentMessageFixture({
            entry_id: "a1",
            role: "assistant",
            content: "当前模型已核对。",
            stop_reason: "stop",
          }),
        ]),
        assistant: agentMessageFixture({ entry_id: "a1", role: "assistant", content: "当前模型已核对。" }),
        status: "idle",
      });
    });
  });

  it("cancels the active session and the local provider request", async () => {
    mocks.sendAgentTurn.mockImplementationOnce((_projectRoot, _sessionId, _question, signal: AbortSignal) => (
      new Promise((_resolve, reject) => {
        signal.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
      })
    ));
    mount();

    fireEvent.change(await screen.findByRole("textbox", { name: "Ask Agent" }), {
      target: { value: "停止前先检查可见证据。" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send to Agent" }));
    const stop = await screen.findByRole("button", { name: "Stop Agent" });
    fireEvent.click(stop);

    await waitFor(() => expect(mocks.abortAgentTurn).toHaveBeenCalledWith(
      "/proj",
      "agent_chain_new",
    ));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("cancelled"));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it.each([
    ["HTTP 500", new ApiError(500, "Cancellation service failed", "AGENT_ABORT_FAILED")],
    ["network failure", new TypeError("Failed to fetch")],
    ["a different HTTP 409", new ApiError(409, "The current owner cannot be interrupted", "AGENT_TURN_OWNED")],
    ["the inactive code with a failed HTTP status", new ApiError(500, "Cancellation service failed", "AGENT_TURN_NOT_ACTIVE")],
  ])("keeps the original request and offers retry when stopping fails with %s", async (_label, failure) => {
    let signal!: AbortSignal;
    mocks.sendAgentTurn.mockImplementationOnce((_root, _session, _question, activeSignal: AbortSignal) => {
      signal = activeSignal;
      return new Promise((_resolve, reject) => {
        signal.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
      });
    });
    mocks.abortAgentTurn.mockRejectedValueOnce(failure);
    mount();
    fireEvent.change(await screen.findByRole("textbox", { name: "Ask Agent" }), { target: { value: "Inspect the original turn." } });
    fireEvent.click(screen.getByRole("button", { name: "Send to Agent" }));
    fireEvent.click(await screen.findByRole("button", { name: "Stop Agent" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/server may still be running.*retry/i);
    expect(signal.aborted).toBe(false);
    expect(screen.getByRole("status")).not.toHaveTextContent("cancelled");
    expect(screen.getByRole("button", { name: "Stop Agent" })).toBeEnabled();
    expect(mocks.sendAgentTurn).toHaveBeenCalledTimes(1);
    expect(mocks.continueAgentTurn).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Stop Agent" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("cancelled"));
    expect(mocks.abortAgentTurn).toHaveBeenCalledTimes(2);
    expect(signal.aborted).toBe(true);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("restores the server turn start and reports pending validation without publishing a draft", async () => {
    const now = Date.now();
    const clock = vi.spyOn(Date, "now").mockReturnValue(now);
    mocks.getAgentSession.mockResolvedValue({ ...session("saved"), status: "running" });
    mocks.getAgentTurnState.mockResolvedValue({ turns: [{ turn_id: "external", status: "running", requires_reconcile: false }] });
    let events: AgentEvent[] = [
      { seq: 1, event_type: "turn_start", command_id: "external-command", created_at: new Date(now - 42_000).toISOString(), payload: {} },
      { seq: 2, event_type: "turn_end", command_id: "external-command", created_at: new Date(now - 5_000).toISOString(), payload: { stop_reason: "tool_calls" } },
      { seq: 3, event_type: "turn_start", command_id: "external-command", created_at: new Date(now - 4_000).toISOString(), payload: {} },
      { seq: 4, event_type: "turn_end", command_id: "external-command", created_at: new Date(now - 3_000).toISOString(), payload: { stop_reason: "revised" } },
      { seq: 5, event_type: "turn_start", command_id: "external-command", created_at: new Date(now - 2_000).toISOString(), payload: {} },
      { seq: 6, event_type: "message_start", command_id: "external-command", created_at: new Date(now).toISOString(), payload: { request_id: "public-request" } },
    ].map(event => ({ ...event, schema_version: "agent.event.v1", session_id: "saved", event_id: `clock-${event.seq}` }));
    mocks.getAgentEvents.mockImplementation(async () => ({ events }));
    try {
      render(<MemoryRouter initialEntries={["/?agent_session=saved"]}><AgentSurfaceProvider projectRoot="/proj" runId="run-a">
        <AgentPanel projectRoot="/proj" runId="run-a" composer={<AgentComposer variant="compact" />} />
      </AgentSurfaceProvider></MemoryRouter>);
      await waitFor(() => expect(screen.getByLabelText("Agent execution progress")).toHaveTextContent("42 s"));
      expect(screen.getByLabelText("Agent execution progress")).toHaveTextContent("Waiting for the model");
      expect(screen.getByRole("button", { name: "View Agent activity" })).toHaveTextContent("42s · Waiting for the model");

      events = [...events,
        { ...events[5], event_id: "validation-progress", seq: 7, event_type: "message_progress", payload: { request_id: "public-request", stage: "receiving", validation_pending: true } },
        { ...events[5], event_id: "usage-observation", seq: 8, event_type: "provider_step", payload: {} },
      ];
      await waitFor(() => expect(screen.getByTestId("agent-event-cursor")).toHaveTextContent("events #8"));
      expect(screen.getByLabelText("Agent execution progress")).toHaveTextContent("Working");
      expect(screen.getByLabelText("Agent execution progress")).toHaveTextContent("42 s");
      expect(screen.getByRole("button", { name: "View Agent activity" })).toHaveTextContent("42s · Working");
      expect(screen.queryByText("Waiting for the model")).not.toBeInTheDocument();
      expect(screen.queryByTestId("agent-live-response")).not.toBeInTheDocument();
      expect(screen.queryByTestId("agent-message-assistant")).not.toBeInTheDocument();
      expect(screen.getByRole("log", { name: /Agent transcript/ })).not.toHaveTextContent(/public-request|validation_pending|reasoning_content/);
      expect(mocks.sendAgentTurn).not.toHaveBeenCalled();
      expect(mocks.continueAgentTurn).not.toHaveBeenCalled();
    } finally {
      clock.mockRestore();
    }
  });

  it("retains a restored durable turn after a failed stop instead of replacing it", async () => {
    mocks.getAgentSession.mockResolvedValue({ ...session("saved"), status: "running" });
    mocks.getAgentTurnState.mockResolvedValue({ turns: [{ turn_id: "original-turn", status: "running", requires_reconcile: false }] });
    mocks.abortAgentTurn.mockRejectedValueOnce(new ApiError(500, "Cancellation service failed", "AGENT_ABORT_FAILED"));
    function RecoveryState() {
      const agent = useAgentSurface();
      return <span data-testid="retained-recovery-state">{agent.durableTurns?.map(turn => `${turn.turn_id}:${turn.status}`).join(",")}</span>;
    }
    render(<MemoryRouter initialEntries={["/?agent_session=saved"]}><AgentSurfaceProvider projectRoot="/proj" runId="run-a">
      <AgentPanel projectRoot="/proj" runId="run-a" /><RecoveryState />
    </AgentSurfaceProvider></MemoryRouter>);
    fireEvent.click(await screen.findByRole("button", { name: "Stop Agent" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/server may still be running/i);
    expect(screen.getByTestId("retained-recovery-state")).toHaveTextContent("original-turn:running");
    expect(screen.queryByRole("button", { name: "Resume original turn" })).not.toBeInTheDocument();
    expect(screen.queryByText(/Unfinished turn: running/)).not.toBeInTheDocument();
    expect(screen.queryByTestId("agent-turn-error")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).not.toHaveTextContent("cancelled");
    expect(screen.getByRole("button", { name: "Stop Agent" })).toBeEnabled();
    expect(mocks.sendAgentTurn).not.toHaveBeenCalled();
    expect(mocks.continueAgentTurn).not.toHaveBeenCalled();
    expect(mocks.resumeAgentTurn).not.toHaveBeenCalled();
  });

  it("accepts only the explicit inactive-turn race without reporting a stop failure", async () => {
    let signal!: AbortSignal;
    mocks.sendAgentTurn.mockImplementationOnce((_root, _session, _question, activeSignal: AbortSignal) => {
      signal = activeSignal;
      return new Promise((_resolve, reject) => {
        signal.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
      });
    });
    mocks.abortAgentTurn.mockRejectedValueOnce(new ApiError(409, "This Agent session has no active turn to stop.", "AGENT_TURN_NOT_ACTIVE"));
    mount();
    fireEvent.change(await screen.findByRole("textbox", { name: "Ask Agent" }), { target: { value: "Inspect the original turn." } });
    fireEvent.click(screen.getByRole("button", { name: "Send to Agent" }));
    fireEvent.click(await screen.findByRole("button", { name: "Stop Agent" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("cancelled"));
    expect(signal.aborted).toBe(true);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(mocks.continueAgentTurn).not.toHaveBeenCalled();
  });

  it("binds a run-rail focus to the active model node instead of sending a run pseudo-key", async () => {
    mocks.workbenchState.selectedKey = "run:run-a";
    const modelNode = {
      id: "node-hash-a",
      nodeKey: "node-hash-a",
      opNodeId: "model:ols_1",
      nodeHash: "node-hash-a",
      raw: null,
      stage: "model",
      kind: "model",
      title: "OLS",
      parentStageId: null,
      trust: "ok",
      decisions: [],
      runs: ["run-a"],
    };
    mocks.forest.current = {
      forest: {
        schemaVersion: 4,
        legacy: false,
        nodes: [modelNode],
        edges: [],
        heads: [{
          runId: "run-a",
          headNodeHash: "node-hash-a",
          fromNode: null,
          rerunOf: null,
          rerunReason: null,
          status: "completed",
          createdAt: "2026-07-18T00:00:00Z",
        }],
        familyCount: 1,
        familyRunCount: 1,
      },
      activeRunId: "run-a",
      setActiveRunId: vi.fn(),
    };

    mount();
    fireEvent.change(await screen.findByRole("textbox", { name: "Ask Agent" }), {
      target: { value: "检查当前模型" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send to Agent" }));

    await waitFor(() => expect(mocks.createAgentSession).toHaveBeenCalledWith(
      "/proj",
      expect.objectContaining({
        context_packet: expect.objectContaining({
          selection: expect.objectContaining({
            forest_node_key: "node-hash-a",
          }),
          operation_target: expect.objectContaining({
            owner_run_id: "run-a",
            op_node_id: "model:ols_1",
          }),
        }),
      }),
    ));
  });

  it("does not let a stale detail tab override the newly selected run", async () => {
    const oldModel = {
      id: "node-hash-old",
      nodeKey: "node-hash-old",
      opNodeId: "model:ols_1",
      nodeHash: "node-hash-old",
      raw: null,
      stage: "model",
      kind: "model",
      title: "Old OLS",
      parentStageId: null,
      trust: "ok",
      decisions: [],
      runs: ["run-old"],
    };
    const newModel = {
      ...oldModel,
      id: "node-hash-new",
      nodeKey: "node-hash-new",
      nodeHash: "node-hash-new",
      title: "New OLS",
      runs: ["run-new"],
    };
    mocks.workbenchState.selectedKey = oldModel.nodeKey;
    mocks.lineageModel.current = { nodes: [oldModel, newModel] };
    mocks.forest.current = {
      forest: {
        schemaVersion: 4,
        legacy: false,
        nodes: [oldModel, newModel],
        edges: [],
        heads: [
          {
            runId: "run-new",
            headNodeHash: newModel.nodeHash,
            fromNode: null,
            rerunOf: null,
            rerunReason: null,
            status: "completed",
            createdAt: "2026-07-18T00:00:00Z",
          },
        ],
        familyCount: 2,
        familyRunCount: 2,
      },
      activeRunId: "run-old",
      setActiveRunId: vi.fn(),
    };

    const view = mount();
    (mocks.forest.current as {activeRunId: string}).activeRunId = "run-new";
    view.rerender(
      <MemoryRouter>
        <AgentSurfaceProvider projectRoot="/proj" runId="run-a">
          <AgentPanel projectRoot="/proj" runId="run-a" />
        </AgentSurfaceProvider>
      </MemoryRouter>,
    );
    fireEvent.change(await screen.findByRole("textbox", { name: "Ask Agent" }), {
      target: { value: "检查刚切换的运行" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send to Agent" }));

    expect(await screen.findByText("Current chain · New OLS")).toBeInTheDocument();

    await waitFor(() => expect(mocks.createAgentSession).toHaveBeenCalledWith(
      "/proj",
      expect.objectContaining({
        context_packet: expect.objectContaining({
          selection: expect.objectContaining({
            forest_node_key: "node-hash-new",
          }),
          operation_target: expect.objectContaining({
            owner_run_id: "run-new",
          }),
        }),
      }),
    ));
  });

  it.each([false, true])("acts on a node in another run, including restored selection (%s)", async (restored) => {
    const olsModel = {
      id: "node-ols", nodeKey: "node-ols", opNodeId: "model:ols_1", nodeHash: "node-ols", raw: null,
      stage: "model", kind: "model", title: "ols_robust", parentStageId: null, trust: "ok", decisions: [],
      runs: ["run-ols"],
    };
    const ivModel = { ...olsModel, id: "node-iv", nodeKey: "node-iv", opNodeId: "model:iv_2sls_1",
                      nodeHash: "node-iv", title: "iv_2sls", runs: ["run-iv"] };
    const head = (runId: string, hash: string) => ({ runId, headNodeHash: hash, fromNode: null, rerunOf: null,
                                                     rerunReason: null, status: "completed", createdAt: null });
    mocks.workbenchState.selectedKey = restored ? ivModel.nodeKey : null;
    mocks.workbenchState.agentFocus = null;
    mocks.lineageModel.current = { nodes: [olsModel, ivModel] };
    mocks.forest.current = {
      forest: { schemaVersion: 4, legacy: false, nodes: [olsModel, ivModel], edges: [],
                heads: [head("run-ols", "node-ols"), head("run-iv", "node-iv")], familyCount: 2, familyRunCount: 2 },
      activeRunId: "run-ols",
      setActiveRunId: vi.fn(),
    };
    const view = mount();
    mocks.workbenchState.selectedKey = ivModel.nodeKey;  // a canvas click on the IV node
    view.rerender(
      <MemoryRouter>
        <AgentSurfaceProvider projectRoot="/proj" runId="run-a">
          <AgentPanel projectRoot="/proj" runId="run-a" />
        </AgentSurfaceProvider>
      </MemoryRouter>,
    );
    expect(await screen.findByText("Run run-iv · iv_2sls")).toBeInTheDocument();
    fireEvent.change(await screen.findByRole("textbox", { name: "Ask Agent" }), { target: { value: "这个节点是什么" } });
    fireEvent.click(screen.getByRole("button", { name: "Send to Agent" }));
    await waitFor(() => expect(mocks.createAgentSession).toHaveBeenCalledWith(
      "/proj",
      expect.objectContaining({
        chain_id: "chain:run-iv",
        run_id: "run-iv",
        context_packet: expect.objectContaining({
          selection: expect.objectContaining({ forest_node_key: "node-iv" }),
        }),
      }),
    ));
  });

  it("hydrates a durable session after reload", async () => {
    sessionStorage.setItem(
      "workbench:agent-session:/proj:run-a:project%3Arun-a%3Anone",
      "agent_chain_saved",
    );
    mocks.getAgentSession.mockResolvedValue(session("agent_chain_saved", [
      agentMessageFixture({ entry_id: "a1", role: "assistant", content: "可回放的回答。", stop_reason: "stop" }),
    ]));

    mount();

    await waitFor(() => expect(mocks.getAgentSession).toHaveBeenCalledWith("/proj", "agent_chain_saved"));
    expect(await screen.findByText("可回放的回答。")).toBeInTheDocument();
  });

  it("hydrates durable navigation links without duplicating them in the Agent transcript", async () => {
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
    expect(screen.queryByRole("button", { name: /open source model/i })).not.toBeInTheDocument();
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
    // A decided proposal leaves the approval bar; the conversation keeps a receipt.
    expect(await screen.findByTestId("agent-proposal-proposal-1")).toHaveTextContent("Approved");
    expect(screen.queryByRole("button", { name: "Confirm proposal proposal-1" })).toBeNull();
  });

  it("continues exactly once after a successful confirmation in both Ask and Auto", async () => {
    for (const mode of ["ask", "auto"]) {
      mocks.continueAgentTurn.mockClear();
      mocks.confirmAgentProposal.mockClear();
      sessionStorage.setItem("workbench:agent-session:/proj:run-a:project%3Arun-a%3Anone", "agent_chain_saved");
      mocks.getAgentSession.mockResolvedValue(session("agent_chain_saved", [], [pendingProposal]));
      let finish!: (value: unknown) => void;
      mocks.confirmAgentProposal.mockReturnValue(new Promise(resolve => { finish = resolve; }));
      mocks.continueAgentTurn.mockResolvedValue({session:session("agent_chain_saved"),status:"idle"});
      const view = mount();
      const confirm = await screen.findByRole("button", {name:"Confirm proposal proposal-1"});
      fireEvent.change(screen.getByRole("combobox", {name:"Agent execution mode"}), {target:{value:mode}});
      fireEvent.click(confirm);
      fireEvent.click(confirm);
      expect(mocks.continueAgentTurn).not.toHaveBeenCalled();
      await act(async () => finish({proposal:{...pendingProposal,status:"confirmed"},
        operation:{record_id:"record-1",operation_id:"model.rerun",status:"completed"}}));
      await waitFor(() => expect(mocks.continueAgentTurn).toHaveBeenCalledTimes(1));
      expect(mocks.confirmAgentProposal).toHaveBeenCalledTimes(1);
      expect(mocks.continueAgentTurn).toHaveBeenCalledWith("/proj", "agent_chain_saved",
        expect.objectContaining({execution_mode:mode}), expect.any(AbortSignal));
      expect(screen.queryByRole("button", {name:"Continue Agent"})).not.toBeInTheDocument();
      view.unmount();
    }
  });

  it("does not continue after the user stops a pending confirmation", async () => {
    sessionStorage.setItem("workbench:agent-session:/proj:run-a:project%3Arun-a%3Anone", "agent_chain_saved");
    mocks.getAgentSession.mockResolvedValue(session("agent_chain_saved", [], [pendingProposal]));
    let finish!: (value: unknown) => void;
    mocks.confirmAgentProposal.mockReturnValue(new Promise(resolve => { finish = resolve; }));
    mount();
    fireEvent.click(await screen.findByRole("button", {name:"Confirm proposal proposal-1"}));
    fireEvent.click(await screen.findByRole("button", {name:"Stop Agent"}));
    await act(async () => finish({proposal:{...pendingProposal,status:"confirmed"},
      operation:{record_id:"record-1",operation_id:"model.rerun",status:"completed"}}));
    expect(mocks.continueAgentTurn).not.toHaveBeenCalled();
  });

  it("confirms checked same-turn reruns serially with each source binding and continues once", async () => {
    sessionStorage.setItem("workbench:agent-session:/proj:run-a:project%3Arun-a%3Anone", "agent_chain_saved");
    const first = {...pendingProposal,command_id:"turn"};
    const second = {...first,proposal_id:"proposal-2",fingerprint:"fp-2",revision:2};
    mocks.getAgentCapabilities.mockResolvedValue(agentCapabilitiesFixture({capabilities:[operationCapabilityFixture({operation_id:"model.rerun"})]}));
    mocks.getAgentSession.mockResolvedValue(session("agent_chain_saved", [], [first,second]));
    let finish!: (value: unknown) => void;
    mocks.confirmAgentProposal.mockImplementation((_root,_session,id) => id === first.proposal_id
      ? new Promise(resolve => {finish=resolve;})
      : Promise.resolve({proposal:{...second,status:"confirmed"},operation:{record_id:"op-2",operation_id:"model.rerun",status:"completed"}}));
    mount();
    fireEvent.click(await screen.findByRole("button",{name:"Run selected proposals"}));
    expect(mocks.confirmAgentProposal).toHaveBeenCalledTimes(1);
    expect(mocks.continueAgentTurn).not.toHaveBeenCalled();
    await act(async () => finish({proposal:{...first,status:"confirmed"},operation:{record_id:"op-1",operation_id:"model.rerun",status:"completed"}}));
    await waitFor(() => expect(mocks.continueAgentTurn).toHaveBeenCalledTimes(1));
    expect(mocks.confirmAgentProposal).toHaveBeenNthCalledWith(1,"/proj","agent_chain_saved","proposal-1",{revision:1,fingerprint:"fingerprint-1",active_head_run_id:"run-a"});
    expect(mocks.confirmAgentProposal).toHaveBeenNthCalledWith(2,"/proj","agent_chain_saved","proposal-2",{revision:2,fingerprint:"fp-2",active_head_run_id:"run-a"});
  });

  it.each(["stop", "unmount"].flatMap(action => ["confirmation", "delay", "reconcile"].map(phase => ({action,phase}))))(
    "ends confirmation polling after $action during $phase without cancelling the authorized operation", async ({action,phase}) => {
      sessionStorage.setItem("workbench:agent-session:/proj:run-a:project%3Arun-a%3Anone", "agent_chain_saved");
      const first = {...pendingProposal,command_id:"turn"};
      mocks.getAgentCapabilities.mockResolvedValue(agentCapabilitiesFixture({capabilities:[operationCapabilityFixture({operation_id:"model.rerun"})]}));
      mocks.getAgentSession.mockResolvedValue(session("agent_chain_saved",[],[first,{...first,proposal_id:"proposal-2"}]));
      let finishConfirmation!: (value:unknown)=>void, finishReconcile!: (value:unknown)=>void;
      mocks.confirmAgentProposal.mockReturnValue(new Promise(resolve=>{finishConfirmation=resolve;}));
      mocks.reconcileAgentOperation.mockReturnValue(new Promise(resolve=>{finishReconcile=resolve;}));
      const view = mount();
      const run = await screen.findByRole("button",{name:"Run selected proposals"});
      vi.useFakeTimers();
      try {
        fireEvent.click(run);
        const response = {proposal:{...first,status:"confirmed"},operation:{record_id:"op-1",operation_id:"model.rerun",status:"running"}};
        if (phase !== "confirmation") await act(async()=>finishConfirmation(response));
        if (phase === "reconcile") {
          await act(async()=>vi.advanceTimersByTimeAsync(1500));
          expect(mocks.reconcileAgentOperation).toHaveBeenCalledTimes(1);
        }
        if (action === "unmount") view.unmount();
        else fireEvent.click(screen.getByRole("button",{name:"Stop Agent"}));
        if (phase === "confirmation") await act(async()=>finishConfirmation(response));
        if (phase === "reconcile") await act(async()=>finishReconcile({operation:response.operation}));
        await act(async()=>vi.advanceTimersByTimeAsync(3000));
        expect(mocks.reconcileAgentOperation).toHaveBeenCalledTimes(phase === "reconcile" ? 1 : 0);
        expect(mocks.confirmAgentProposal).toHaveBeenCalledTimes(1);
        expect(mocks.continueAgentTurn).not.toHaveBeenCalled();
        expect(mocks.abortAgentTurn).not.toHaveBeenCalled();
      } finally {
        view.unmount();
        vi.useRealTimers();
      }
    },
  );

  it.each(["failed", "cancelled", "stale", "error", "stop", "switch", "unmount"])("stops a batch after %s without confirming the next item or continuing", async outcome => {
    sessionStorage.setItem("workbench:agent-session:/proj:run-a:project%3Arun-a%3Anone", "agent_chain_saved");
    sessionStorage.setItem("workbench:agent-session:/proj:run-b:project%3Arun-b%3Anone", "session-b");
    const first = {...pendingProposal,command_id:"turn"};
    const second = {...first,proposal_id:"proposal-2",fingerprint:"fp-2"};
    mocks.getAgentCapabilities.mockResolvedValue(agentCapabilitiesFixture({capabilities:[operationCapabilityFixture({operation_id:"model.rerun"})]}));
    mocks.getAgentSession.mockImplementation(async (_root,id) => session(id, [], id === "agent_chain_saved" ? [first,second] : []));
    let finish!: (value:unknown) => void, fail!: (error:Error) => void;
    mocks.confirmAgentProposal.mockReturnValue(new Promise((resolve,reject) => {finish=resolve;fail=reject;}));
    const view = mount();
    fireEvent.click(await screen.findByRole("button",{name:"Run selected proposals"}));
    if (outcome === "stop") fireEvent.click(await screen.findByRole("button",{name:"Stop Agent"}));
    if (outcome === "switch") {
      view.rerender(<MemoryRouter><AgentSurfaceProvider projectRoot="/proj" runId="run-b"><AgentPanel projectRoot="/proj" runId="run-b" /></AgentSurfaceProvider></MemoryRouter>);
      await waitFor(() => expect(mocks.getAgentSession).toHaveBeenCalledWith("/proj","session-b"));
    }
    if (outcome === "unmount") view.unmount();
    await act(async () => {
      if (outcome === "error") fail(new Error("Source validation failed"));
      else finish({proposal:{...first,status:"confirmed"},operation:{record_id:"op-1",operation_id:"model.rerun",status:["stop","switch","unmount"].includes(outcome)?"completed":outcome}});
    });
    expect(mocks.confirmAgentProposal).toHaveBeenCalledTimes(1);
    expect(mocks.continueAgentTurn).not.toHaveBeenCalled();
    if (!["switch","unmount"].includes(outcome)) {
      if (outcome === "error") {
        expect(screen.getByRole("checkbox",{name:"Select proposal proposal-2"})).toBeInTheDocument();
        expect(screen.getByText("Source validation failed")).toBeInTheDocument();
      } else {
        expect(screen.getByRole("button",{name:"Confirm proposal proposal-2"})).toBeInTheDocument();
        expect(screen.getByTestId("agent-proposal-proposal-1")).toHaveTextContent("Approved");
      }
    }
  });

  it("leaves unchecked proposals pending and continues only after the checked subset", async () => {
    sessionStorage.setItem("workbench:agent-session:/proj:run-a:project%3Arun-a%3Anone", "agent_chain_saved");
    const first = {...pendingProposal,command_id:"turn"};
    const second = {...first,proposal_id:"proposal-2",fingerprint:"fp-2"};
    mocks.getAgentCapabilities.mockResolvedValue(agentCapabilitiesFixture({capabilities:[operationCapabilityFixture({operation_id:"model.rerun"})]}));
    mocks.getAgentSession.mockResolvedValue(session("agent_chain_saved",[],[first,second]));
    mocks.continueAgentTurn.mockResolvedValue({session:session("agent_chain_saved",[],[{...first,status:"confirmed"},second]),status:"idle"});
    mocks.confirmAgentProposal.mockResolvedValue({proposal:{...first,status:"confirmed"},operation:{record_id:"op-1",operation_id:"model.rerun",status:"completed"}});
    mount();
    fireEvent.click(await screen.findByRole("checkbox",{name:"Select proposal proposal-2"}));
    fireEvent.click(screen.getByRole("button",{name:"Run selected proposals"}));
    await waitFor(() => expect(mocks.continueAgentTurn).toHaveBeenCalledTimes(1));
    expect(mocks.confirmAgentProposal).toHaveBeenCalledTimes(1);
    expect(mocks.confirmAgentProposal.mock.calls[0][2]).toBe("proposal-1");
    expect(mocks.declineAgentProposal).not.toHaveBeenCalled();
    expect(screen.getByRole("button",{name:"Confirm proposal proposal-2"})).toBeInTheDocument();
  });

  it("retains earlier approvals when a later item fails and leaves the rest pending", async () => {
    sessionStorage.setItem("workbench:agent-session:/proj:run-a:project%3Arun-a%3Anone", "agent_chain_saved");
    const proposals = [1,2,3].map(n => ({...pendingProposal,command_id:"turn",proposal_id:`proposal-${n}`,fingerprint:`fp-${n}`}));
    mocks.getAgentCapabilities.mockResolvedValue(agentCapabilitiesFixture({capabilities:[operationCapabilityFixture({operation_id:"model.rerun"})]}));
    mocks.getAgentSession.mockResolvedValue(session("agent_chain_saved",[],proposals));
    mocks.confirmAgentProposal.mockImplementation(async (_root,_session,id) => ({proposal:{...proposals.find(p=>p.proposal_id===id),status:"confirmed"},
      operation:{record_id:id,operation_id:"model.rerun",status:id==="proposal-1"?"completed":"failed"}}));
    mount();
    fireEvent.click(await screen.findByRole("button",{name:"Run selected proposals"}));
    await screen.findByText("Operation proposal-2 failed. Remaining proposals were not run.");
    expect(mocks.confirmAgentProposal).toHaveBeenCalledTimes(2);
    expect(mocks.continueAgentTurn).not.toHaveBeenCalled();
    expect(screen.getByTestId("agent-proposal-proposal-1")).toHaveTextContent("Approved");
    expect(screen.getByTestId("agent-proposal-proposal-2")).toHaveTextContent("Approved");
    expect(screen.getByRole("button",{name:"Confirm proposal proposal-3"})).toBeInTheDocument();
  });

  it("does not surface an old batch error in another conversation in the same view", async () => {
    sessionStorage.setItem("workbench:agent-session:/proj:run-a:project%3Arun-a%3Anone", "agent_chain_saved");
    const first = {...pendingProposal,command_id:"turn"};
    mocks.getAgentCapabilities.mockResolvedValue(agentCapabilitiesFixture({capabilities:[operationCapabilityFixture({operation_id:"model.rerun"})]}));
    mocks.getAgentSession.mockImplementation(async (_root,id) => session(id,[],id==="agent_chain_saved"?[first,{...first,proposal_id:"proposal-2"}]:[]));
    let fail!: (error:Error)=>void;
    mocks.confirmAgentProposal.mockReturnValue(new Promise((_resolve,reject)=>{fail=reject;}));
    function SwitchConversation() {
      const agent = useAgentSurface();
      return <button onClick={()=>agent.openConversation?.("other-session")}>Switch conversation</button>;
    }
    render(<MemoryRouter><AgentSurfaceProvider projectRoot="/proj" runId="run-a"><AgentPanel projectRoot="/proj" runId="run-a" /><SwitchConversation /></AgentSurfaceProvider></MemoryRouter>);
    fireEvent.click(await screen.findByRole("button",{name:"Run selected proposals"}));
    fireEvent.click(screen.getByRole("button",{name:"Switch conversation"}));
    await waitFor(()=>expect(mocks.getAgentSession).toHaveBeenCalledWith("/proj","other-session"));
    await act(async()=>fail(new Error("Old batch failure")));
    expect(screen.queryByText("Old batch failure")).not.toBeInTheDocument();
    expect(mocks.confirmAgentProposal).toHaveBeenCalledTimes(1);
    expect(mocks.continueAgentTurn).not.toHaveBeenCalled();
  });

  it("does not continue a confirmed proposal after switching sessions", async () => {
    sessionStorage.setItem("workbench:agent-session:/proj:run-a:project%3Arun-a%3Anone", "agent_chain_saved");
    sessionStorage.setItem("workbench:agent-session:/proj:run-b:project%3Arun-b%3Anone", "session-b");
    mocks.getAgentSession.mockImplementation((_root, id) => Promise.resolve(session(id, [], id === "agent_chain_saved" ? [pendingProposal] : [])));
    let finish!: (value: unknown) => void;
    mocks.confirmAgentProposal.mockReturnValue(new Promise(resolve => { finish = resolve; }));
    const view = mount();
    fireEvent.click(await screen.findByRole("button", {name:"Confirm proposal proposal-1"}));
    view.rerender(<MemoryRouter><AgentSurfaceProvider projectRoot="/proj" runId="run-b"><AgentPanel projectRoot="/proj" runId="run-b" /></AgentSurfaceProvider></MemoryRouter>);
    await waitFor(() => expect(mocks.getAgentSession).toHaveBeenCalledWith("/proj", "session-b"));
    await act(async () => finish({proposal:{...pendingProposal,status:"confirmed"},
      operation:{record_id:"record-1",operation_id:"model.rerun",status:"completed"}}));
    expect(mocks.continueAgentTurn).not.toHaveBeenCalled();
  });

  it("confirms a project Main proposal against its source rather than the visible run", async () => {
    sessionStorage.setItem("workbench:agent-session:/proj:run-a:project%3Arun-a%3Anone", "agent_main_saved");
    const proposal = {...pendingProposal, preconditions:{active_head_run_id:"run-source"}};
    mocks.getAgentSession.mockResolvedValue({...session("agent_main_saved", [], [proposal]), role:"main"});
    mount();
    fireEvent.click(await screen.findByRole("button", {name:"Confirm proposal proposal-1"}));
    await waitFor(() => expect(mocks.confirmAgentProposal).toHaveBeenCalledWith("/proj", "agent_main_saved", "proposal-1",
      {revision:1, fingerprint:"fingerprint-1", active_head_run_id:"run-source"}));
  });

  it("confirms a linked proposal against its bound chain rather than another visible run", async () => {
    const proposal = {...pendingProposal, preconditions: {active_head_run_id: "run-source"}};
    mocks.getAgentSession.mockResolvedValue(session("agent_linked", [], [proposal]));
    render(<MemoryRouter initialEntries={["/?agent_session=agent_linked"]}>
      <AgentSurfaceProvider projectRoot="/proj" runId="run-other"><AgentPanel projectRoot="/proj" runId="run-other" /></AgentSurfaceProvider>
    </MemoryRouter>);
    fireEvent.click(await screen.findByRole("button", {name: "Confirm proposal proposal-1"}));
    await waitFor(() => expect(mocks.confirmAgentProposal).toHaveBeenCalledWith("/proj", "agent_linked", "proposal-1",
      {revision: 1, fingerprint: "fingerprint-1", active_head_run_id: "run-source"}));
    expect(screen.getByText("Linked Agent session")).toBeInTheDocument();
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
    // A decided proposal leaves the approval bar; the conversation keeps a receipt.
    expect(await screen.findByTestId("agent-proposal-proposal-1")).toHaveTextContent("Declined");
    expect(screen.queryByRole("button", { name: "Confirm proposal proposal-1" })).toBeNull();
  });

  it("revises a visible proposal through the scoped Agent API", async () => {
    sessionStorage.setItem(
      "workbench:agent-session:/proj:run-a:project%3Arun-a%3Anone",
      "agent_chain_saved",
    );
    mocks.getAgentSession.mockResolvedValue(session("agent_chain_saved", [], [pendingProposal]));

    mount();

    fireEvent.click(await screen.findByRole("button", { name: "Revise proposal proposal-1" }));
    fireEvent.change(screen.getByLabelText("Proposal changes proposal-1.covariance.new"), {
      target: { value: "unadjusted" },
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

describe("the conversation a view continues", () => {
  beforeEach(() => {
    sessionStorage.clear();
    localStorage.clear();
    vi.clearAllMocks();
    mocks.lineageModel.current = { nodes: [] };
    mocks.workbenchState.selectedKey = null;
    mocks.workbenchState.agentFocus = null;
    mocks.forest.current = null;
    mocks.fetchLlmProviders.mockResolvedValue({ active_provider_id: provider.id, providers: [provider] });
    mocks.fetchLlmConfig.mockResolvedValue(config);
    mocks.getAgentEvents.mockResolvedValue({ events: [] });
  });

  it("is kept when loading fails for a reason other than 404, and forgotten on 404", async () => {
    const key = "workbench:agent-session:/proj:run-a:project%3Arun-a%3Anone";
    localStorage.setItem(key, "agent_chain_kept");
    mocks.getAgentSession.mockRejectedValueOnce(Object.assign(new Error("Failed to fetch"), { status: 0 }));
    const first = mount();
    await waitFor(() => expect(mocks.getAgentSession).toHaveBeenCalled());
    await waitFor(() => expect(localStorage.getItem(key)).toBe("agent_chain_kept"));
    first.unmount();
    mocks.getAgentSession.mockRejectedValueOnce(Object.assign(new Error("not found"), { status: 404 }));
    mount();
    await waitFor(() => expect(localStorage.getItem(key)).toBeNull());
  });
});
