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

const sessionPath = (sessionId: string, suffix: string) => `/agent/sessions/${encodeURIComponent(sessionId)}${suffix}`;

/** Go back to just before one of your messages; its text is returned. */
export function rewindAgentSession(
  projectRoot: string,
  sessionId: string,
  entryId: string,
): Promise<ResponseOf<"/agent/sessions/{session_id}/rewind", "post">> {
  return request(agentPath(projectRoot, sessionPath(sessionId, "/rewind")), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ entry_id: entryId }),
  });
}

/** A new conversation sharing this one up to a message. */
export function forkAgentSession(
  projectRoot: string,
  sessionId: string,
  entryId: string,
): Promise<ResponseOf<"/agent/sessions/{session_id}/fork", "post">> {
  return request(agentPath(projectRoot, sessionPath(sessionId, "/fork")), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ entry_id: entryId }),
  });
}

/** The project's conversations, most recently active first. */
export function listAgentConversations(
  projectRoot: string,
  includeArchived = false,
): Promise<ResponseOf<"/agent/conversations", "get">> {
  const query = new URLSearchParams({ project_root: projectRoot });
  if (includeArchived) query.set("include_archived", "true");
  return request(apiUrl(`/agent/conversations?${query.toString()}`));
}

/** Rename, archive or restore a conversation. */
export function updateAgentConversation(
  projectRoot: string,
  sessionId: string,
  body: RequestOf<"/agent/conversations/{session_id}", "patch">,
): Promise<ResponseOf<"/agent/conversations/{session_id}", "patch">> {
  return request(agentPath(projectRoot, `/agent/conversations/${encodeURIComponent(sessionId)}`), {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/** Delete a conversation's messages; the analysis ledger is kept. */
export function deleteAgentConversation(
  projectRoot: string,
  sessionId: string,
): Promise<ResponseOf<"/agent/conversations/{session_id}", "delete">> {
  return request(agentPath(projectRoot, `/agent/conversations/${encodeURIComponent(sessionId)}`), { method: "DELETE" });
}

/** Summarize the earlier conversation now; the newest part stays verbatim. */
export function compactAgentSession(
  projectRoot: string,
  sessionId: string,
  focus?: string,
): Promise<ResponseOf<"/agent/sessions/{session_id}/compact", "post">> {
  return request(agentPath(projectRoot, sessionPath(sessionId, "/compact")), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(focus ? { focus } : {}),
  });
}

/** The built-in guide and the personal and project AGENTS.md. */
export function getAgentInstructions(projectRoot: string): Promise<ResponseOf<"/agent/instructions", "get">> {
  return request(agentPath(projectRoot, "/agent/instructions"));
}

export function saveAgentInstructions(
  projectRoot: string,
  body: RequestOf<"/agent/instructions", "put">,
): Promise<ResponseOf<"/agent/instructions", "put">> {
  return request(agentPath(projectRoot, "/agent/instructions"), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/** The project template filled with this project's datasets and models. */
export function draftAgentInstructions(projectRoot: string): Promise<ResponseOf<"/agent/instructions/draft", "get">> {
  return request(agentPath(projectRoot, "/agent/instructions/draft"));
}

export function pinAgentChapter(
  projectRoot: string,
  sessionId: string,
  entryId: string,
  title: string,
): Promise<ResponseOf<"/agent/sessions/{session_id}/chapters", "post">> {
  return request(agentPath(projectRoot, sessionPath(sessionId, "/chapters")), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ entry_id: entryId, title }),
  });
}

export function unpinAgentChapter(
  projectRoot: string,
  sessionId: string,
  entryId: string,
): Promise<ResponseOf<"/agent/sessions/{session_id}/chapters/{entry_id}", "delete">> {
  return request(agentPath(projectRoot, sessionPath(sessionId, `/chapters/${encodeURIComponent(entryId)}`)), { method: "DELETE" });
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
  executionPolicy: "auto_read_only" | "proposal_only" = "auto_read_only",
): Promise<ResponseOf<"/agent/sessions/{session_id}/turns", "post">> {
  return request(
    agentPath(projectRoot, `/agent/sessions/${encodeURIComponent(sessionId)}/turns`),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({question, execution_policy: executionPolicy, ...(contextPacket ? {context_packet: contextPacket} : {})}),
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
