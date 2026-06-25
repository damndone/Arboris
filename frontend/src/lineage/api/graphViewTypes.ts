// frontend/src/lineage/api/graphViewTypes.ts
//
// GraphViewModel — the stable UI-facing shape consumed by all V1.5.0 lineage
// components. Produced by `graphAdapter.adaptRunGraph(...)` from the V1.4.x
// backend `GraphResponse`. Components never import backend `LineageNode`
// directly; that boundary is what makes future backend changes (V2.0 Pipeline
// split, V1.5.x added fields) localised refactors.
//
// Spec: docs/superpowers/specs/2026-05-22-v1.5.0-uiux-integration-design.md §4

export type Stage =
  | "source"
  | "eda"
  | "clean"
  | "transform"
  | "model"
  | "diag"
  | "viz"
  | "report"
  | "unknown"; // adapter fallback when backend has no stage field

export type Trust = "ok" | "review" | "caution";

// Full V1.4.1 backend enum preserved — no information loss.
export type DecisionReviewStatus =
  | "not_needed"
  | "needed"
  | "passed"
  | "failed"
  | "waived"
  | "unknown";

export interface DecisionViewModel {
  id: string; // ← decision_id
  question: string; // decisionRegistry humanised title
  picked: string; // ← selected (safe-formatted; non-string → "")
  alternatives: string[]; // ← candidates (safe-formatted; non-string[] → [])
  why: string; // ← reason.explanation || decisionRegistry fallback || ""
  evidence: string[]; // backend/registry-derived when available; [] if absent
  reviewStatus: DecisionReviewStatus;

  // Forward-compat slots — V1.5.0 always undefined
  requiresConfirmation?: boolean;
  confirmedBy?: string;
  confirmedAt?: string;
}

export interface ArtifactRef {
  name: string;
  mime: string;
  sizeBytes?: number;
  sha256?: string;
  url?: string; // signed download URL (V2.0)
}

/**
 * Editable form control descriptor. V1.5.0 declares the shape but does not
 * consume it; V1.5.2+ adapter and OperationSection will populate & render.
 * Mirrors `EditableControl` in uiux/handoff/api.openapi.yaml.
 */
export interface EditableControl {
  kind:
    | "radio"
    | "select"
    | "multiselect"
    | "slider"
    | "text"
    | "textarea"
    | "toggle"
    | "columns"; // v1.6.1: aligned with backend editable_schema (column-picker)
  key: string;
  label: string;
  value?: unknown;
  options?: Array<string | { value: unknown; label: string }>;
  min?: number;
  max?: number;
  step?: number;
  unit?: string;
  // v1.6.1: backend-aligned annotations (correct the stale v1.5.0 shape).
  role?: string; // semantic role (e.g. "model" — the op_type switch control)
  required?: boolean;
  visible_when?: Record<string, unknown>; // forward-compat; preserved, not yet enforced
}

export interface GraphViewNode {
  // ── identity (V1.5.0 populated) ──
  id: string; // backend stable id; serves React Flow node.id
  nodeKey: string; // logical key (alias of id today; UUID-split in V2.0)
  raw: unknown; // original backend node payload, for Raw JSON / debugging

  // ── core display (V1.5.0 populated) ──
  stage: Stage;
  kind: string; // ← backend kind verbatim (e.g. "model", "dataset_stage")
  title: string; // ← display_label
  subtitle?: string; // adapter-derived from existing fields only
  summary?: string; // ← summary
  parentStageId: string | null; // ← parent_stage_id (used by folding + path builder)

  // ── trust (V1.5.0 populated; adapter normalised — see graphAdapter.normalizeTrust) ──
  trust: Trust;
  trustReason?: string; // ← trust_reason

  // ── decisions (V1.5.0 populated) ──
  decisions: DecisionViewModel[];

  // ── timing (V1.5.0 populated where backend provides) ──
  createdAt?: string; // ← created_at

  // ── forward-compat slots — V1.5.0 undefined ──
  runtimeMs?: number; // populate when backend exposes NodeExecution stats
  status?:
    | "queued"
    | "running"
    | "waiting_review"
    | "done"
    | "failed"
    | "cancelled";

  // ── extension slots — V1.5.0 always undefined ──
  artifacts?: ArtifactRef[];
  stats?: Record<string, unknown>;
  coefficients?: Array<{
    name: string;
    est: number;
    ci: [number, number];
    p: number;
  }>;
  preview?: Array<Record<string, unknown>>;
  schemaFields?: Array<{
    name: string;
    type: string;
    missing: number;
    hist?: number[];
  }>;
  code?: { lang: string; body: string }; // V1.5.1+ read-only
  editableSchema?: EditableControl[]; // V1.5.2+
}

export interface GraphViewEdge {
  id: string;
  source: string;
  target: string;
  op?: string;
  reversible?: boolean;
  inverseOp?: string | null;
}

export interface GraphViewModel {
  schemaVersion: number;
  runId: string;
  legacy: boolean;
  nodes: GraphViewNode[];
  edges: GraphViewEdge[];
  stats: {
    nodeCount: number;
    edgeCount: number;
    leafCount: number;
    hasDpCount: number;
  };
}

// ───────────────────────────────────────────────────────────────
// v1.6.1 — head-set (cross-run lineage forest) contract + ViewModel
// Backend: GET /runs/{id}/graph?view=headset (lineage/headset.py::build_headset)
// ───────────────────────────────────────────────────────────────

export interface CasRef {
  node_hash: string;
  artifact: string;
}

/** Raw backend NodeView — a per-run graph node decorated with node-hash identity
 *  + editable annotation. Keyed in the response by its dedup key (node_hash, or the
 *  bare node_id for non-cacheable nodes like the raw upload). */
export interface HeadSetNodeRaw {
  id: string;
  kind: string;
  display_label: string;
  stage?: string | null;
  summary?: string | null;
  trust?: unknown;
  trust_reason?: string | null;
  parent_stage_id?: string | null;
  created_at?: string;
  decision_points?: unknown[];
  node_hash: string | null;
  producing_stage: string | null;
  cas_ref: CasRef | null;
  runs: string[];
  editable?: boolean;
  op_type?: string;
  schema_id?: string;
  editable_schema?: EditableControl[];
  editable_schema_source?: "capabilities" | "run_inputs";
}

export interface HeadSetEdgeRaw {
  source: string;
  target: string;
}

export interface HeadRaw {
  run_id: string;
  head_node_hash: string | null;
  from_node: string | null;
  rerun_of: string | null;
  rerun_reason: string | null;
  status: string | null;
  created_at: string | null;
}

export interface HeadSetResponse {
  nodes: Record<string, HeadSetNodeRaw>;
  edges: HeadSetEdgeRaw[];
  heads: HeadRaw[];
  schema_version: number;
  legacy: boolean;
}

/** UI-facing forest node: the base GraphViewNode plus head-set identity + editability.
 *  `id`/`nodeKey` are the dedup key (node_hash or bare node_id) — unique in the forest,
 *  unlike `opNodeId` (the original per-run node id, reused as the rerun `from_node`). */
export interface HeadSetNode extends GraphViewNode {
  opNodeId: string;
  nodeHash: string | null;
  producingStage: string | null;
  casRef: CasRef | null;
  runs: string[];
  editable?: boolean;
  opType?: string;
  schemaId?: string;
  editableSchema?: EditableControl[];
  editableSchemaSource?: "capabilities" | "run_inputs";
}

export interface Head {
  runId: string;
  headNodeHash: string | null;
  fromNode: string | null;
  rerunOf: string | null;
  rerunReason: string | null;
  status: string | null;
  createdAt: string | null;
}

export interface ForestViewModel {
  schemaVersion: number;
  legacy: boolean;
  nodes: HeadSetNode[];
  edges: GraphViewEdge[];
  heads: Head[];
}

/** Resolve which run owns a (possibly deduped) forest node for a rerun / display.
 *  A node shared across runs (`runs.length > 1`) has no single owner, so prefer the
 *  active head when it's one of them — that's the version the user is viewing and the
 *  parent whose form the rerun must fork from. Otherwise fall back to the first run
 *  that owns the node. Returns undefined only when `runs` is empty/absent. */
export function resolveOwnerRun(
  runs: string[] | undefined,
  activeRunId: string | undefined,
): string | undefined {
  if (activeRunId && runs?.includes(activeRunId)) return activeRunId;
  return runs?.[0];
}
