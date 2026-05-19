// frontend/src/lineage/types.ts
// Types matching backend GET /runs/:id/graph response (V1.4.1 schema_version=2).

export type NodeKind =
  | "dataset_stage"
  | "variable"
  | "operation"
  | "model"
  | "test"
  | "plot"
  | "report";

export type Trust = "ok" | "caution" | "warning" | "blocker";

export type DecisionSource =
  | "user_explicit"
  | "system_default"
  | "data_driven_default"
  | "fallback"
  | "compatibility_constraint";

export type ReasonType =
  | "system_default"
  | "data_driven_default"
  | "user_config"
  | "fallback"
  | "compatibility_constraint";

export type ReviewStatus =
  | "not_needed"
  | "needed"
  | "passed"
  | "failed"
  | "waived"
  | "unknown";

export interface Contestability {
  is_contestable: boolean;
  assumption_checks_needed: string[];
  warnings: string[];
  review_status: ReviewStatus;
}

export interface AutoChosenReason {
  reason_type: ReasonType;
  explanation: string | null;
  chosen_params_schema: string | null;
  chosen_params: Record<string, unknown>;
}

export interface DecisionPoint {
  decision_id: string;
  decision_id_alias: string[];
  selected: unknown;
  candidates: unknown[];
  source: DecisionSource;
  contestability: Contestability;
  reason: AutoChosenReason | null;
}

export interface LineageNode {
  id: string;
  kind: NodeKind;
  display_label: string;
  summary: string | null;
  created_at: string;
  parent_stage_id: string | null;
  branch_id: string;
  trust: Trust;
  trust_reason: string | null;
  archived: boolean;
  payload_ref: string | null;
  decision_points: DecisionPoint[];
  annotations: unknown[];
}

export interface LineageEdge {
  id: string;
  source_id: string;
  target_id: string;
  op: string;
  params: Record<string, unknown>;
  reversible: boolean;
  inverse_op: string | null;
}

export interface BranchRef {
  id: string;
  forked_from_node_id: string | null;
  head_node_ids: string[];
  archived: boolean;
}

export interface GraphStats {
  node_count: number;
  edge_count: number;
  leaf_count: number;
  has_dp_count: number;
}

export interface GraphResponse {
  schema_version: 1 | 2;
  run_id: string;
  legacy: boolean;
  stats: GraphStats;
  nodes: Record<string, LineageNode>;
  edges: Record<string, LineageEdge>;
  branches: Record<string, BranchRef>;
}
