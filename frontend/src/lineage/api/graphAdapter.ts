// frontend/src/lineage/api/graphAdapter.ts
//
// Adapter: V1.4.x backend `GraphResponse` → V1.5.0 UI `GraphViewModel`.
//
// Rules:
//   - never fabricate data (no fields synthesised from polymorphic JSON)
//   - safe formatters on polymorphic inputs (safeString, safeStringArray)
//   - unknown schema_version throws — UI surfaces as "corrupt graph"
//   - additive backend fields are tolerated; unrecognised fields ignored
//
// Spec §4 / §5.

import type {
  DecisionPoint,
  GraphResponse,
  LineageEdge,
  LineageNode,
  Trust as BackendTrust,
} from "../types";
import { getDPDisplay } from "../decisions/decisionRegistry";
import type {
  DecisionReviewStatus,
  DecisionViewModel,
  ForestViewModel,
  GraphViewEdge,
  GraphViewModel,
  GraphViewNode,
  Head,
  HeadSetNode,
  HeadSetNodeRaw,
  HeadSetResponse,
  Stage,
  Trust,
} from "./graphViewTypes";

// ───────────────────────────────────────────────────────────────
// Error class
// ───────────────────────────────────────────────────────────────

/**
 * Thrown when the adapter receives a graph whose `schema_version` is not
 * explicitly supported. UI surfaces this as a "corrupt graph" error state
 * (same path V1.4.1 uses for HTTP 422 responses).
 */
export class UnsupportedGraphSchemaError extends Error {
  readonly schemaVersion: number;
  constructor(schemaVersion: number) {
    super(`Unsupported graph schema_version: ${schemaVersion}`);
    this.name = "UnsupportedGraphSchemaError";
    this.schemaVersion = schemaVersion;
  }
}

// ───────────────────────────────────────────────────────────────
// Safe formatters
// ───────────────────────────────────────────────────────────────

export function safeString(v: unknown, fallback = ""): string {
  return typeof v === "string" ? v : fallback;
}

export function safeStringArray(v: unknown): string[] {
  return Array.isArray(v)
    ? v.filter((x): x is string => typeof x === "string")
    : [];
}

// ───────────────────────────────────────────────────────────────
// Trust normalisation (spec §4.4)
// ───────────────────────────────────────────────────────────────

const UNKNOWN_TRUST_WARNED = new Set<string>();

export function normalizeTrust(t: unknown): Trust {
  if (t === "ok") return "ok";
  if (t === "warning") return "review";
  if (t === "caution" || t === "blocker") return "caution";
  const key = String(t);
  if (!UNKNOWN_TRUST_WARNED.has(key)) {
    UNKNOWN_TRUST_WARNED.add(key);
    // eslint-disable-next-line no-console
    console.warn(
      `[graphAdapter] unrecognised trust value ${JSON.stringify(t)}; falling back to "review"`,
    );
  }
  return "review";
}

// Test-only helper: reset the warn-once cache between tests.
export function _resetTrustWarnings(): void {
  UNKNOWN_TRUST_WARNED.clear();
}

// ───────────────────────────────────────────────────────────────
// Decision-point mapping
// ───────────────────────────────────────────────────────────────

function adaptDecisionPoint(dp: DecisionPoint): DecisionViewModel {
  const reg = getDPDisplay(dp.decision_id);
  const reviewStatus: DecisionReviewStatus =
    dp.contestability?.review_status ?? "unknown";

  return {
    id: dp.decision_id,
    question: reg.title || dp.decision_id,
    picked: safeString(dp.selected),
    alternatives: safeStringArray(dp.candidates),
    why: safeString(dp.reason?.explanation, ""),
    evidence: [], // V1.5.0: never fabricate; future versions populate
    reviewStatus,
  };
}

// ───────────────────────────────────────────────────────────────
// Node / edge mapping (shared between v2 and v3)
// ───────────────────────────────────────────────────────────────

const STAGE_VALUES: ReadonlySet<string> = new Set([
  "source",
  "eda",
  "clean",
  "transform",
  "model",
  "diag",
  "viz",
  "report",
]);

function coerceStage(s: unknown): Stage {
  return typeof s === "string" && STAGE_VALUES.has(s) ? (s as Stage) : "unknown";
}

function adaptNode(
  raw: LineageNode & { stage?: string | null },
  stageSource: "v2" | "v3",
): GraphViewNode {
  const stage: Stage =
    stageSource === "v2" ? "unknown" : coerceStage(raw.stage);
  const subtitle = stage !== "unknown" ? `${stage} · ${raw.kind}` : undefined;

  // Defensive coalesce (REV-3 #4): if a future backend ever stamps v3 but
  // omits decision_points entirely, fall back to [] instead of crashing on
  // `.map of undefined`. The contract requires the field, but production
  // shouldn't melt over a missing additive.
  const dps = raw.decision_points ?? [];

  return {
    id: raw.id,
    nodeKey: raw.id, // V1.5.0: same; V2.0 may diverge
    raw,
    stage,
    kind: raw.kind,
    title: raw.display_label,
    subtitle,
    summary: raw.summary ?? undefined,
    parentStageId: raw.parent_stage_id ?? null,
    trust: normalizeTrust(raw.trust as BackendTrust),
    trustReason: raw.trust_reason ?? undefined,
    decisions: dps.map(adaptDecisionPoint),
    createdAt: raw.created_at,
  };
}

function adaptEdge(raw: LineageEdge): GraphViewEdge {
  return {
    id: raw.id,
    source: raw.source_id,
    target: raw.target_id,
    op: raw.op || undefined,
    reversible: raw.reversible,
    inverseOp: raw.inverse_op,
  };
}

// ───────────────────────────────────────────────────────────────
// Schema-specific entry points
// ───────────────────────────────────────────────────────────────

function adaptGraphSchemaV2(backend: GraphResponse): GraphViewModel {
  return adaptCore(backend, "v2");
}

function adaptGraphSchemaV3(backend: GraphResponse): GraphViewModel {
  return adaptCore(backend, "v3");
}

function adaptCore(
  backend: GraphResponse,
  stageSource: "v2" | "v3",
): GraphViewModel {
  return {
    schemaVersion: backend.schema_version,
    runId: backend.run_id,
    legacy: backend.legacy,
    nodes: Object.values(backend.nodes).map((n) =>
      adaptNode(n as LineageNode & { stage?: string | null }, stageSource),
    ),
    edges: Object.values(backend.edges).map(adaptEdge),
    stats: {
      nodeCount: backend.stats.node_count,
      edgeCount: backend.stats.edge_count,
      leafCount: backend.stats.leaf_count,
      hasDpCount: backend.stats.has_dp_count,
    },
  };
}

// ───────────────────────────────────────────────────────────────
// Top-level adapter
// ───────────────────────────────────────────────────────────────

/**
 * Top-level adapter for Run-scoped graphs. V2.0 will introduce a sibling
 * `adaptPipelineGraph` (Pipeline-as-entity) without retconning this name.
 *
 * Note: `schema_version` is cast to `number` so the dispatcher can compare
 * against `3` even though the V1.4.x type definition is still `1 | 2`. After
 * T3.7 widens the type, the cast becomes redundant but harmless.
 */
export function adaptRunGraph(backend: GraphResponse): GraphViewModel {
  const ver = backend.schema_version as number;
  if (ver === 2) return adaptGraphSchemaV2(backend);
  if (ver === 3) return adaptGraphSchemaV3(backend);
  throw new UnsupportedGraphSchemaError(ver);
}

// ───────────────────────────────────────────────────────────────
// v1.6.1 — head-set (cross-run forest) adapter
// ───────────────────────────────────────────────────────────────

function adaptHeadSetNode(key: string, raw: HeadSetNodeRaw): HeadSetNode {
  const stage = coerceStage(raw.stage);
  const dps = (raw.decision_points ?? []) as DecisionPoint[];
  return {
    // The dedup KEY (node_hash, or bare node_id for non-cacheable nodes) is the forest
    // identity — node_id alone is NOT unique across sibling reruns (M1/M2 share an id).
    id: key,
    nodeKey: key,
    opNodeId: raw.id,
    raw,
    stage,
    kind: raw.kind,
    title: raw.display_label,
    subtitle: stage !== "unknown" ? `${stage} · ${raw.kind}` : undefined,
    summary: raw.summary ?? undefined,
    parentStageId: raw.parent_stage_id ?? null,
    trust: normalizeTrust(raw.trust as BackendTrust),
    trustReason: raw.trust_reason ?? undefined,
    decisions: dps.map(adaptDecisionPoint),
    createdAt: raw.created_at,
    nodeHash: raw.node_hash,
    producingStage: raw.producing_stage,
    casRef: raw.cas_ref,
    runs: raw.runs ?? [],
    editable: raw.editable,
    opType: raw.op_type,
    schemaId: raw.schema_id,
    editableSchema: raw.editable_schema,
    editableSchemaSource: raw.editable_schema_source,
  };
}

/**
 * Adapt the backend head-set response into the forest ViewModel. The backend has
 * already deduped nodes by node_hash (shared prefixes appear once); this maps each
 * entry, camelCases the heads, and synthesizes edge ids from source/target dedup keys.
 */
export function adaptHeadSet(backend: HeadSetResponse): ForestViewModel {
  // Legacy / degraded target: the backend returns the OLD per-run graph shape
  // (legacy:true, NO `heads`, and `edges` is a dict-by-id — not the head-set's
  // edge array). Don't try to adapt it as a forest; return a legacy marker so the
  // route degrades to a notice instead of throwing on `dict.map`.
  if (backend.legacy || !Array.isArray(backend.heads)) {
    return {
      schemaVersion: backend.schema_version ?? 0,
      legacy: true,
      nodes: [],
      edges: [],
      heads: [],
    };
  }
  const nodes: HeadSetNode[] = Object.entries(backend.nodes ?? {}).map(
    ([key, raw]) => adaptHeadSetNode(key, raw),
  );
  const edges: GraphViewEdge[] = (backend.edges ?? []).map((e) => ({
    id: `${e.source}->${e.target}`,
    source: e.source,
    target: e.target,
  }));
  const heads: Head[] = (backend.heads ?? []).map((h) => ({
    runId: h.run_id,
    headNodeHash: h.head_node_hash,
    fromNode: h.from_node,
    rerunOf: h.rerun_of,
    rerunReason: h.rerun_reason,
    status: h.status,
    createdAt: h.created_at,
  }));
  return {
    schemaVersion: backend.schema_version,
    legacy: backend.legacy,
    nodes,
    edges,
    heads,
  };
}
