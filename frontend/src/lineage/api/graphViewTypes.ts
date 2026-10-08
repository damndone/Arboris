// frontend/src/lineage/api/graphViewTypes.ts
//
// GraphViewModel — the stable UI-facing shape consumed by all V1.5.0 lineage
// components. Produced by `graphAdapter.adaptRunGraph(...)` from the V1.4.x
// backend `GraphResponse`. Components never import backend `LineageNode`
// directly; that boundary is what makes future backend changes (V2.0 Pipeline
// split, V1.5.x added fields) localised refactors.
//
// Spec: docs/superpowers/archive/specs/2026-05-22-v1.5.0-uiux-integration-design.md §4

import type { Schema } from "../../apiTypes";
import type { RerunFromProvenance } from "./nodeOperationContext";

export type Stage =
  | "source"
  | "eda"
  | "clean"
  | "transform"
  | "model"
  | "diag"
  | "viz"
  | "report"
  | "compare" // v1.8 slice C: a durable comparison joining two model nodes
  | "unknown"; // adapter fallback when backend has no stage field

// v1.6.6 ④: `blocker` is its own strongest variant (backend Trust.BLOCKER)
// — it used to collapse into `caution`, hiding hard-blocking problems.
export type Trust = "ok" | "review" | "caution" | "blocker";

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

/** A node's artifact as the graph serves it (dataset profile, cleaning
 *  actions, confirmed explorations). */
export type ArtifactRef = Schema<"NodeArtifact">;

/** Editable form control descriptor, as the backend declares it. */
export type EditableControl = Schema<"EditableControlSpec">;

/** v1.6.7 — lifecycle of an in-graph draft node (draft-in-graph feature).
 *  Undefined on real forest nodes. See spec §3. */
export type LifecycleState =
  | "draft"
  | "validating"
  | "valid"
  | "invalid"
  | "pending"
  | "executed"
  | "failed";

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

  // ── v1.6.7 draft-in-graph (undefined for real forest nodes) ──
  isDraft?: boolean;
  lifecycleState?: LifecycleState;
  draftId?: string;

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
  /** v1.6.5 — edge params (e.g. role-bearing var->model edges carry
   *  `{ role, source, estimator_family, dropped }`). Optional; only
   *  populated by the single-run graph adapter. */
  params?: Record<string, unknown>;
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

export type CasRef = Schema<"CasRef">;

/** A per-run graph node decorated with node-hash identity and the editable
 *  annotation, keyed in the response by its dedup key (node_hash, or the bare
 *  node_id for non-cacheable nodes like the raw upload). */
export type HeadSetNodeRaw = Schema<"ForestNodeView">;
export type HeadSetEdgeRaw = Schema<"ForestEdge">;
export type HeadRaw = Schema<"ForestHead">;
export type HeadSetFamilyRaw = Schema<"ForestFamily">;
export type HeadSetResponse = Schema<"ForestGraph">;

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
  /** Node-level provenance: the source this node was rerun from. */
  rerunFrom?: RerunFromProvenance;
  /** Set instead of rerunFrom when the runs sharing the node record different sources. */
  rerunFromConflicts?: RerunFromProvenance[];
  runRerunFrom?: RerunFromProvenance;
}

export interface Head {
  runId: string;
  headNodeHash: string | null;
  fromNode: string | null;
  rerunOf: string | null;
  rerunReason: string | null;
  status: string | null;
  createdAt: string | null;
  runRerunFrom?: RerunFromProvenance | null;
}

export interface ForestViewModel {
  schemaVersion: number;
  legacy: boolean;
  nodes: HeadSetNode[];
  edges: GraphViewEdge[];
  heads: Head[];
  familyCount: number;
  familyRunCount: number;
}

/** Legacy resolver for old rerun / display paths only.
 *  UNSAFE for new node operations: it cannot represent ambiguous ownership,
 *  operation targets, node hashes, lineage paths, or context diagnostics.
 *
 *  New node operation consumers must use `resolveNodeOperationContext`.
 *
 *  Resolve which run owns a (possibly deduped) forest node for a rerun / display.
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
