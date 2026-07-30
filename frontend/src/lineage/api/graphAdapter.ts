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
  if (t === "caution") return "caution";
  if (t === "blocker") return "blocker"; // v1.6.6 ④: keep BLOCKER distinct
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
  "compare",
]);

function coerceStage(s: unknown): Stage {
  return typeof s === "string" && STAGE_VALUES.has(s) ? (s as Stage) : "unknown";
}

function displayTitle(
  raw: { display_label: string },
  stage: Stage,
  isTerminal = false,
): string {
  // A report is one representation of the run output, not the output's
  // identity. Keep the persisted stage/type unchanged while presenting every
  // terminal report node as the format-neutral Result to users.
  return stage === "report" && isTerminal ? "Result" : raw.display_label;
}

function adaptNode(
  raw: LineageNode & { stage?: string | null },
  stageSource: "v2" | "v3",
  isTerminal = false,
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
    title: displayTitle(raw, stage, isTerminal),
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
    params: raw.params,
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
  const rawEdges = Object.values(backend.edges);
  const nodeIdsWithChildren = new Set(rawEdges.map((edge) => edge.source_id));
  return {
    schemaVersion: backend.schema_version,
    runId: backend.run_id,
    legacy: backend.legacy,
    nodes: Object.values(backend.nodes).map((n) =>
      adaptNode(
        n as LineageNode & { stage?: string | null },
        stageSource,
        !nodeIdsWithChildren.has(n.id),
      ),
    ),
    edges: rawEdges.map(adaptEdge),
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
  return adaptHeadSetNodeWithRunProvenance(key, raw);
}

function adaptHeadSetNodeWithRunProvenance(
  key: string,
  raw: HeadSetNodeRaw,
  runRerunFrom?: HeadSetNode["runRerunFrom"],
  isTerminal = false,
): HeadSetNode {
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
    title: displayTitle(raw, stage, isTerminal),
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
    // v1.6.11 A2 — dataset schema/profile preview flows into the Ask AI packet.
    artifacts: raw.artifacts,
    // v1.6.11 C-2 — model fit metrics + coefficients flow into the fact table.
    stats: raw.stats,
    editable: raw.editable,
    opType: raw.op_type,
    schemaId: raw.schema_id,
    editableSchema: raw.editable_schema,
    editableSchemaSource: raw.editable_schema_source,
    editableSchemaVersion: raw.editable_schema_version,
    rerunFrom: raw.rerun_from,
    runRerunFrom,
  };
}

/**
 * Adapt the backend head-set response into the forest ViewModel. The backend has
 * already deduped nodes by node_hash (shared prefixes appear once); this maps each
 * entry, camelCases the heads, and synthesizes edge ids from source/target dedup keys.
 */
export function adaptHeadSet(backend: HeadSetResponse): ForestViewModel {
  const familyCount = Array.isArray(backend.families)
    ? backend.families.length
    : 0;
  const familyRunCount = Array.isArray(backend.families)
    ? new Set(backend.families.flatMap((family) => family.members)).size
    : 0;
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
      familyCount,
      familyRunCount,
    };
  }
  const heads: Head[] = (backend.heads ?? []).map((h) => ({
    runId: h.run_id,
    headNodeHash: h.head_node_hash,
    fromNode: h.from_node,
    rerunOf: h.rerun_of,
    rerunReason: h.rerun_reason,
    status: h.status,
    createdAt: h.created_at,
    runRerunFrom: h.rerun_from ?? null,
  }));
  const runRerunFromByRun = new Map(
    heads
      .filter((head) => head.runRerunFrom)
      .map((head) => [head.runId, head] as const),
  );
  const rawEdges = backend.edges ?? [];
  const nodeKeysWithChildren = new Set(rawEdges.map((edge) => edge.source));
  const nodes: HeadSetNode[] = Object.entries(backend.nodes ?? {}).map(
    ([key, raw]) => {
      const runRerunFrom = findConservativeRunRerunFromForNode(
        key,
        raw,
        runRerunFromByRun,
      );
      return adaptHeadSetNodeWithRunProvenance(
        key,
        raw,
        runRerunFrom,
        !nodeKeysWithChildren.has(key),
      );
    },
  );
  const edges: GraphViewEdge[] = rawEdges.map((e) => ({
    id: `${e.source}->${e.target}`,
    source: e.source,
    target: e.target,
    // v1.6.5 — carry role op + params into the forest view model so the
    // canvas renders variable roles (role lives on the edge).
    op: e.op || undefined,
    params: e.params ?? undefined,
  }));
  return {
    schemaVersion: backend.schema_version,
    legacy: backend.legacy,
    nodes,
    edges,
    heads,
    familyCount,
    familyRunCount,
  };
}

function findConservativeRunRerunFromForNode(
  key: string,
  raw: HeadSetNodeRaw,
  headByRun: Map<string, Head>,
): HeadSetNode["runRerunFrom"] {
  if (raw.runs.length !== 1 || !raw.produced_by_rerun_request_id) {
    return undefined;
  }
  const head = headByRun.get(raw.runs[0]);
  const rerunFrom = head?.runRerunFrom ?? undefined;
  if (!head || !rerunFrom) {
    return undefined;
  }
  if (
    head.fromNode !== raw.id ||
    raw.produced_by_rerun_request_id !== rerunFrom.rerun_request_id
  ) {
    return undefined;
  }
  return rerunFrom;
}
