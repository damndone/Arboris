export type AgentRole = "main" | "chain";

export type AgentMessage = {
  entry_id: string;
  role: "user" | "assistant" | "tool";
  content: string;
  /** Tool entries: the executed tool id (used as the typed status label). */
  name?: string | null;
  stop_reason?: string | null;
  error?: string | null;
  navigation?: AgentNavigationRef[];
};

export type AgentNavigationRef = {
  kind:
    | "graph_node"
    | "agent_session"
    | "agent_entry"
    | "chain"
    | "fork"
    | "run"
    | "operation"
    | "diff"
    | "proposal";
  id: string;
  label: string;
  relation: "source" | "parent" | "child" | "result" | "audit" | "context";
  available: boolean;
  href: {
    view: "graph" | "agent";
    run_id?: string;
    node_ref?: string;
    node_hash?: string;
    forest_node_key?: string;
    session_id?: string;
    chain_id?: string;
    entry_id?: string;
    fork_id?: string;
    operation_record_id?: string;
    diff?: string;
    proposal_id?: string;
  };
  reason?: string;
};

export type AgentNavigationProjection = {
  subject: AgentNavigationRef;
  links: AgentNavigationRef[];
  last_event_seq: number;
  hierarchy?: AgentHierarchyNode | null;
};

export type AgentHierarchyNode = {
  ref: AgentNavigationRef;
  status: string | null;
  children: AgentHierarchyNode[];
};

export type AgentActivityItem = {
  kind: "operation";
  activity_id: string;
  at: string;
  main: AgentNavigationRef;
  chain: AgentNavigationRef;
  operation: AgentNavigationRef;
  diff: AgentNavigationRef | null;
  status: string;
  links: AgentNavigationRef[];
  diff_ref: Record<string, unknown> | null;
  verification: Record<string, unknown>;
  effect_status?: string;
  projection_status?: string;
};

export type AgentActivityEventItem = {
  kind: "event";
  activity_id: string;
  at: string;
  seq: number;
  event_type: string;
  session: AgentNavigationRef;
  main: AgentNavigationRef;
  chain: AgentNavigationRef;
  command_id: string | null;
  details: Record<string, unknown>;
  links: AgentNavigationRef[];
};

export type AgentEvent = {
  schema_version?: string;
  event_id: string;
  session_id: string;
  seq: number;
  event_type: string;
  payload: Record<string, unknown>;
  command_id: string | null;
  created_at: string;
};

export type AgentProposal = {
  record_type: "revision";
  proposal_id: string;
  operation_id: string;
  operation_version: string;
  revision: number;
  session_id: string;
  chain_id: string;
  command_id: string | null;
  target: Record<string, unknown>;
  preconditions: Record<string, unknown>;
  changes: Record<string, unknown>;
  evidence_refs: string[];
  expected_effect: string[];
  risks: string[];
  created_at: string;
  fingerprint: string;
  status: string;
  confirmation?: Record<string, unknown>;
  decision?: Record<string, unknown>;
};

export type AgentOperationRecord = {
  record_id: string;
  operation_id: string;
  proposal_id: string;
  status: string;
  [key: string]: unknown;
};

export type AgentSession = {
  session_id: string;
  role: AgentRole;
  chain_id: string;
  status: string;
  context_fingerprint: string | null;
  model: string | null;
  provider_id: string | null;
  context_window_tokens: number | null;
  messages: AgentMessage[];
  proposals: AgentProposal[];
};

export type AgentContextPacket = Record<string, unknown>;

export type AgentModelOption = {
  display_name: string;
  request_model: string;
  context_window_tokens: number | null;
  supports_1m: boolean;
};

export type AgentCapability = {
  operation_id: string;
  operation_version: string;
  effect_level: string;
  scope: string;
  scope_requirements: string[];
  risk_level: string;
  confirmation_policy: string;
  ui_description: string;
  example_prompts: string[];
  natural_language_enabled: boolean;
};

export type AgentCapabilityBoundaryItem = {
  id: string;
  label: string;
  description: string;
};

export type AgentCapabilityCatalog = {
  capabilities: AgentCapability[];
  boundary: {
    advisory: AgentCapabilityBoundaryItem[];
    unsupported: AgentCapabilityBoundaryItem[];
  };
};

export type AgentSessionCreateRequest = {
  role: AgentRole;
  chain_id?: string;
  run_id?: string;
  context_packet: AgentContextPacket;
};
