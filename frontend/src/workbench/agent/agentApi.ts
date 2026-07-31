import { apiUrl, readResponse } from "../../api";
import type {
  AgentContextPacket,
  AgentCapabilityCatalog,
  AgentActivityItem,
  AgentActivityEventItem,
  AgentEvent,
  AgentHierarchyNode,
  AgentNavigationProjection,
  AgentNavigationRef,
  AgentOperationRecord,
  AgentProposal,
  AgentSession,
  AgentSessionCreateRequest,
} from "./agentTypes";

function agentPath(projectRoot: string, path: string): string {
  return apiUrl(`${path}?project_root=${encodeURIComponent(projectRoot)}`);
}

export function getAgentCapabilities(
  projectRoot: string,
  scope?: string,
): Promise<AgentCapabilityCatalog> {
  const query = new URLSearchParams({ project_root: projectRoot });
  if (scope) query.set("scope", scope);
  return request<AgentCapabilityCatalog>(apiUrl(`/agent/capabilities?${query.toString()}`));
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

export function agentAuditExportUrl(
  projectRoot: string,
  sessionId: string,
  format: "html" | "markdown" | "json" = "html",
): string {
  const query = new URLSearchParams({ project_root: projectRoot, format });
  return apiUrl(
    `/agent/sessions/${encodeURIComponent(sessionId)}/audit?${query.toString()}`,
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

export function getAgentActivity(
  projectRoot: string,
): Promise<{
  activities: AgentActivityItem[];
  events: AgentActivityEventItem[];
  hierarchy?: AgentHierarchyNode | null;
}> {
  return request(agentPath(projectRoot, "/agent/activity"));
}

export type AgentForkProposalResponse = {
  session_id: string;
  source_session_entry_id: string;
  proposal: AgentProposal;
  navigation: AgentNavigationRef;
  status: string;
};

export function createAgentForkProposal(
  projectRoot: string,
  body: {
    session_id?: string | null;
    chain_id?: string | null;
    source_run_id: string;
    source_node_ref: string;
    source_session_entry_id?: string | null;
    active_head_run_id: string;
    reason?: string;
  },
): Promise<AgentForkProposalResponse> {
  return request(agentPath(projectRoot, "/agent/fork-proposals"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
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
  signal?: AbortSignal,
): Promise<{ session: AgentSession; assistant: AgentSession["messages"][number]; status: string }> {
  return request(
    agentPath(projectRoot, `/agent/sessions/${encodeURIComponent(sessionId)}/turns`),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
      signal,
    },
  );
}

/** Request cancellation for the active server-side turn in this session. */
export function abortAgentTurn(
  projectRoot: string,
  sessionId: string,
): Promise<{ status: "cancelling"; session_id: string }> {
  return request(
    agentPath(projectRoot, `/agent/sessions/${encodeURIComponent(sessionId)}/abort`),
    { method: "POST" },
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
