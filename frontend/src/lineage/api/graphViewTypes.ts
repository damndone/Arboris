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
    | "toggle";
  key: string;
  label: string;
  value?: unknown;
  options?: Array<string | { value: unknown; label: string }>;
  min?: number;
  max?: number;
  step?: number;
  unit?: string;
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
