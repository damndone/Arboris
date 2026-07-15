import { apiUrl, readResponse } from "../../api";
import type {
  AgentContextPacket,
  AgentEvent,
  AgentNavigationProjection,
  AgentOperationRecord,
  AgentProposal,
  AgentSession,
  AgentSessionCreateRequest,
} from "./agentTypes";

function agentPath(projectRoot: string, path: string): string {
  return apiUrl(`${path}?project_root=${encodeURIComponent(projectRoot)}`);
}

export function createAgentSession(
  projectRoot: string,
  body: AgentSessionCreateRequest,
): Promise<AgentSession> {
  return request<AgentSession>(agentPath(projectRoot, "/agent/sessions"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function getAgentSession(
  projectRoot: string,
  sessionId: string,
): Promise<AgentSession> {
  return request<AgentSession>(
    agentPath(projectRoot, `/agent/sessions/${encodeURIComponent(sessionId)}`),
  );
}

export function getAgentSessionProjection(
  projectRoot: string,
  sessionId: string,
): Promise<{ projection: AgentNavigationProjection }> {
  return request(
    agentPath(
      projectRoot,
      `/agent/sessions/${encodeURIComponent(sessionId)}/projection`,
    ),
  );
}

export function getAgentGraphNavigation(
  projectRoot: string,
  target: {
    runId: string;
    nodeRef?: string | null;
    forestNodeKey?: string | null;
  },
): Promise<{ projection: AgentNavigationProjection }> {
  const query = new URLSearchParams({
    project_root: projectRoot,
    run_id: target.runId,
  });
  if (target.nodeRef) query.set("node_ref", target.nodeRef);
  if (target.forestNodeKey) query.set("forest_node_key", target.forestNodeKey);
  return request(apiUrl(`/agent/navigation/graph?${query.toString()}`));
}

export function getAgentOperationProjection(
  projectRoot: string,
  sessionId: string,
  recordId: string,
): Promise<{
  operation: AgentOperationRecord;
  projection: AgentNavigationProjection;
}> {
  return request(
    agentPath(
      projectRoot,
      `/agent/sessions/${encodeURIComponent(sessionId)}/operations/${encodeURIComponent(recordId)}`,
    ),
  );
}

export function getAgentEvents(
  projectRoot: string,
  sessionId: string,
  afterSeq = 0,
): Promise<{ events: AgentEvent[] }> {
  return request(
    `${agentPath(projectRoot, `/agent/sessions/${encodeURIComponent(sessionId)}/events`)}&after_seq=${afterSeq}`,
  );
}

export function confirmAgentProposal(
  projectRoot: string,
  sessionId: string,
  proposalId: string,
  body: { revision: number; fingerprint: string; active_head_run_id: string },
): Promise<{
  proposal: AgentProposal;
  operation: AgentOperationRecord;
  status: string;
}> {
  return request(
    agentPath(
      projectRoot,
      `/agent/sessions/${encodeURIComponent(sessionId)}/proposals/${encodeURIComponent(proposalId)}/confirm`,
    ),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
}

export function declineAgentProposal(
  projectRoot: string,
  sessionId: string,
  proposalId: string,
  reason?: string,
): Promise<{ proposal: AgentProposal; status: string }> {
  return request(
    agentPath(
      projectRoot,
      `/agent/sessions/${encodeURIComponent(sessionId)}/proposals/${encodeURIComponent(proposalId)}/decline`,
    ),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(reason ? { reason } : {}),
    },
  );
}

export function reviseAgentProposal(
  projectRoot: string,
  sessionId: string,
  proposalId: string,
  body: {
    base_revision: number;
    changes: Record<string, unknown>;
    expected_effect?: string[];
    risks?: string[];
  },
): Promise<{ proposal: AgentProposal; status: string }> {
  return request(
    agentPath(
      projectRoot,
      `/agent/sessions/${encodeURIComponent(sessionId)}/proposals/${encodeURIComponent(proposalId)}/revise`,
    ),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
}

export function reconcileAgentOperation(
  projectRoot: string,
  sessionId: string,
  recordId: string,
): Promise<{ operation: AgentOperationRecord; status: string }> {
  return request(
    agentPath(
      projectRoot,
      `/agent/sessions/${encodeURIComponent(sessionId)}/operations/${encodeURIComponent(recordId)}/reconcile`,
    ),
    { method: "POST" },
  );
}

export async function sendAgentTurn(
  projectRoot: string,
  sessionId: string,
  question: string,
): Promise<{ session: AgentSession; assistant: AgentSession["messages"][number]; status: string }> {
  return request(
    agentPath(projectRoot, `/agent/sessions/${encodeURIComponent(sessionId)}/turns`),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    },
  );
}

export function fallbackProjectContext(runId: string, selectedKey: string | null): AgentContextPacket {
  return {
    packet_version: "agent-context/v1",
    context_fingerprint: `project:${runId}:${selectedKey ?? "none"}`,
    selection: { forest_node_key: selectedKey ?? `run:${runId}` },
    response_guardrails: {
      advisory_text_only: true,
      graph_mutations_allowed: false,
    },
  };
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  return readResponse<T>(response);
}
