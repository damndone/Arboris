export interface DomainMemoryPreferences {
  cross_project_domain_memory_use: boolean;
  cross_project_domain_memory_iteration: boolean;
}

export interface DomainMemoryRequestOverride {
  cross_project_domain_memory_use?: boolean | null;
  cross_project_domain_memory_iteration?: boolean | null;
}

export interface DomainMemoryScope {
  namespace_id: string;
  profile_id: string;
  owner_id: string;
  organization_id: string | null;
  visibility_scope: "private" | "organization";
  promotion_scope: "user" | "organization";
}

export interface DomainMemoryHint {
  memory_id: string;
  revision: number;
  content_hash: string;
  memory_kind: string;
  domain_tags: string[];
  compact_lesson: string;
  recommended_effect_kind: string;
  recommended_target_refs: string[];
  source_summary_refs: string[];
  match_reason: string[];
  apply_mode?: "inform_only" | "suggest_default";
  apply_mode_reason?: string;
  memory_source?: { memory_id: string; revision: number };
}

export interface DomainMemoryRetrievalProjection {
  contract_version?: "domain-memory-context-input/v1" | "domain-memory-context-input/v2";
  retrieval_ref?: string;
  scope_ref?: string;
  outcome: "used" | "not_used" | "empty" | "blocked";
  reason: string;
  entries: DomainMemoryHint[];
  omissions: Array<{ memory_id: string; revision: number; reason: string }>;
  bounded: boolean;
  preference_ref?: string;
  memory_authority?: "non_authoritative";
}

export interface DomainMemoryCandidate {
  candidate_id: string;
  revision: number;
  status: "proposed" | "needs_review" | "approved" | "rejected" | "expired";
  memory_kind: string;
  compact_lesson: string;
  source_summary_refs: string[];
}
