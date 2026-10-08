import { apiUrl, readResponse } from "../../api";
import type { RequestOf, ResponseOf } from "../../apiTypes";
import type { AgentContextPacket } from "./agentTypes";

function agentPath(projectRoot: string, path: string): string {
  return apiUrl(`${path}?project_root=${encodeURIComponent(projectRoot)}`);
}

export function getAgentCapabilities(
  projectRoot: string,
  scope?: string,
): Promise<ResponseOf<"/agent/capabilities", "get">> {
  const query = new URLSearchParams({ project_root: projectRoot });
  if (scope) query.set("scope", scope);
  return request(apiUrl(`/agent/capabilities?${query.toString()}`));
}

export function createAgentSession(
  projectRoot: string,
  body: RequestOf<"/agent/sessions", "post">,
): Promise<ResponseOf<"/agent/sessions", "post">> {
  return request(agentPath(projectRoot, "/agent/sessions"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function getAgentSession(
  projectRoot: string,
  sessionId: string,
): Promise<ResponseOf<"/agent/sessions/{session_id}", "get">> {
  return request(
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
): Promise<ResponseOf<"/agent/sessions/{session_id}/projection", "get">> {
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
): Promise<ResponseOf<"/agent/navigation/graph", "get">> {
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
): Promise<ResponseOf<"/agent/sessions/{session_id}/operations/{record_id}", "get">> {
  return request(
    agentPath(
      projectRoot,
      `/agent/sessions/${encodeURIComponent(sessionId)}/operations/${encodeURIComponent(recordId)}`,
    ),
  );
}

export function getAgentActivity(
  projectRoot: string,
): Promise<ResponseOf<"/agent/activity", "get">> {
  return request(agentPath(projectRoot, "/agent/activity"));
}

export type AgentForkProposalResponse = ResponseOf<"/agent/fork-proposals", "post">;

export function createAgentForkProposal(
  projectRoot: string,
  body: RequestOf<"/agent/fork-proposals", "post">,
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
): Promise<ResponseOf<"/agent/sessions/{session_id}/events", "get">> {
  return request(
    `${agentPath(projectRoot, `/agent/sessions/${encodeURIComponent(sessionId)}/events`)}&after_seq=${afterSeq}`,
  );
}

export function confirmAgentProposal(
  projectRoot: string,
  sessionId: string,
  proposalId: string,
  body: RequestOf<"/agent/sessions/{session_id}/proposals/{proposal_id}/confirm", "post">,
): Promise<ResponseOf<"/agent/sessions/{session_id}/proposals/{proposal_id}/confirm", "post">> {
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
): Promise<ResponseOf<"/agent/sessions/{session_id}/proposals/{proposal_id}/decline", "post">> {
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
  body: RequestOf<"/agent/sessions/{session_id}/proposals/{proposal_id}/revise", "post">,
): Promise<ResponseOf<"/agent/sessions/{session_id}/proposals/{proposal_id}/revise", "post">> {
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
): Promise<ResponseOf<"/agent/sessions/{session_id}/operations/{record_id}/reconcile", "post">> {
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
  contextPacket?: Record<string, unknown>,
): Promise<ResponseOf<"/agent/sessions/{session_id}/turns", "post">> {
  return request(
    agentPath(projectRoot, `/agent/sessions/${encodeURIComponent(sessionId)}/turns`),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(contextPacket ? { question, context_packet: contextPacket } : { question }),
      signal,
    },
  );
}

/** Request cancellation for the active server-side turn in this session. */
export function abortAgentTurn(
  projectRoot: string,
  sessionId: string,
): Promise<ResponseOf<"/agent/sessions/{session_id}/abort", "post">> {
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
