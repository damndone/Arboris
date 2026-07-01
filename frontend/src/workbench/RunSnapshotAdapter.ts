// frontend/src/workbench/RunSnapshotAdapter.ts
//
// V1.5.2 — RunSnapshotAdapter. Plan §5.
//
// Rule: this is a *query / index layer* over `GraphViewModel`. It does
// NOT define a second node type and does NOT mirror backend schema. If
// a backend field is needed, it gets added to `GraphViewModel` (via
// `graphAdapter`) first — never bypassed here.
//
// Why this exists: views beyond Graph (Table, Pipeline) and features
// like search / upstream highlight / lineage chip strips all need
// fast lookups (`byKey`, `byStage`) and graph walks (`upstreamOf`,
// `lineagePathTo`). Building them ad-hoc inside each view would
// scatter the same index code across components. Centralising here
// also keeps walk semantics consistent (same parent-selection rule
// across Drawer chips, canvas highlight, AI scope).

import type {
  GraphViewEdge,
  GraphViewModel,
  GraphViewNode,
  Stage,
} from "../lineage/api/graphViewTypes";
import { ROLE_OF_EDGE_OP, ROLE_GROUP_ORDER, type Role } from "../lineage/roles";

/** Hard cap on graph walks. Mirrors `pathBuilder.MAX_HOPS` to ensure
 *  identical behaviour between Drawer chips and canvas overlays. */
const MAX_HOPS = 100;

/** A searchable item produced by `searchIndex`. Variables, models, and
 *  decisions are projected back to the node that produced them so a
 *  hit can `setSelected(nodeKey)` even if the matched term wasn't the
 *  node title itself. */
export interface SearchItem {
  kind: "node" | "variable" | "model" | "decision";
  /** Human-readable label shown in the search dropdown. */
  label: string;
  /** Lowercased haystack used for substring matching. */
  haystack: string;
  /** Node this item resolves to. `selected = focus = nodeKey` on commit. */
  nodeKey: string;
  /** Optional sub-id (e.g. decision id) for richer rendering. */
  detail?: string;
}

export interface RunSnapshot {
  /** O(1) node lookup by `nodeKey`. */
  nodeByKey: ReadonlyMap<string, GraphViewNode>;
  /** Nodes grouped by stage, preserving insertion order. */
  nodesByStage: ReadonlyMap<Stage, GraphViewNode[]>;
  /** Decisions per node, indexed by `nodeKey`. Empty array if none. */
  decisionsByNode: ReadonlyMap<string, GraphViewNode["decisions"]>;
  /** All variable-like nodes (heuristic: `kind === "variable"` or stage
   *  in {"transform","clean","eda"} with kind ending in "_var"). */
  variables: GraphViewNode[];
  /** All model-like nodes (`kind === "model"` or stage === "model"). */
  models: GraphViewNode[];
  /** Flat searchable item list. Hover-preview + Enter-commit consume
   *  this; substring match happens in the search component, not here. */
  searchIndex: SearchItem[];

  /** Walk the parent chain. Lex-smallest source picked on multi-parent
   *  (mirrors pathBuilder semantics). Cycle / depth-limit safe. */
  upstreamOf(nodeKey: string): GraphViewNode[];
  /** Walk descendants breadth-first. Visited-set deduped. */
  downstreamOf(nodeKey: string): GraphViewNode[];
  /** Ordered path from earliest ancestor to the target (inclusive).
   *  `[]` if `nodeKey` is unknown. */
  lineagePathTo(nodeKey: string): GraphViewNode[];
}

/**
 * Build a RunSnapshot from a GraphViewModel. Pure function — memoise
 * at the caller (the provider) keyed on `model.runId + model.nodes`.
 */
export function buildRunSnapshot(model: GraphViewModel): RunSnapshot {
  const nodeByKey = new Map<string, GraphViewNode>();
  for (const n of model.nodes) nodeByKey.set(n.nodeKey, n);

  const nodesByStage = new Map<Stage, GraphViewNode[]>();
  for (const n of model.nodes) {
    const bucket = nodesByStage.get(n.stage);
    if (bucket) bucket.push(n);
    else nodesByStage.set(n.stage, [n]);
  }

  const decisionsByNode = new Map<string, GraphViewNode["decisions"]>();
  for (const n of model.nodes) decisionsByNode.set(n.nodeKey, n.decisions);

  const variables = model.nodes.filter(isVariableNode);
  const models = model.nodes.filter(isModelNode);

  // Adjacency for fast walks. Built once per snapshot rather than
  // re-scanning `model.edges` on every upstreamOf call.
  const parentsByTarget = buildAdjacency(model.edges, "target");
  const childrenBySource = buildAdjacency(model.edges, "source");

  const searchIndex = buildSearchIndex(model.nodes);

  return {
    nodeByKey,
    nodesByStage,
    decisionsByNode,
    variables,
    models,
    searchIndex,
    upstreamOf(nodeKey) {
      return walk(nodeKey, parentsByTarget, "source", nodeByKey);
    },
    downstreamOf(nodeKey) {
      return walk(nodeKey, childrenBySource, "target", nodeByKey);
    },
    lineagePathTo(nodeKey) {
      const target = nodeByKey.get(nodeKey);
      if (!target) return [];
      const ancestors = walk(
        nodeKey,
        parentsByTarget,
        "source",
        nodeByKey,
      );
      // Ancestors come back farthest-first via BFS; reverse so the
      // earliest source ends up at index 0 and target at the end.
      return [...ancestors.reverse(), target];
    },
  };
}

// ─── helpers ────────────────────────────────────────────────────────

function isVariableNode(n: GraphViewNode): boolean {
  if (n.kind === "variable") return true;
  if (n.kind.endsWith("_var")) return true;
  return false;
}

function isModelNode(n: GraphViewNode): boolean {
  return n.kind === "model" || n.stage === "model";
}

/** Group edges by either `source` or `target`, returning a Map of
 *  the *opposite* endpoint list (so a key's value is its neighbours). */
function buildAdjacency(
  edges: GraphViewEdge[],
  by: "source" | "target",
): Map<string, GraphViewEdge[]> {
  const out = new Map<string, GraphViewEdge[]>();
  for (const e of edges) {
    const key = e[by];
    const bucket = out.get(key);
    if (bucket) bucket.push(e);
    else out.set(key, [e]);
  }
  return out;
}

/**
 * Breadth-first walk along an adjacency map, dedup'd via visited set
 * and capped at MAX_HOPS to mirror pathBuilder.
 * `take` selects which edge endpoint to enqueue next.
 */
function walk(
  startKey: string,
  adjacency: Map<string, GraphViewEdge[]>,
  take: "source" | "target",
  nodeByKey: Map<string, GraphViewNode>,
): GraphViewNode[] {
  if (!nodeByKey.has(startKey)) return [];
  const visited = new Set<string>([startKey]);
  const result: GraphViewNode[] = [];
  let frontier: string[] = [startKey];
  for (let depth = 0; depth < MAX_HOPS && frontier.length > 0; depth++) {
    const next: string[] = [];
    for (const key of frontier) {
      const edges = adjacency.get(key) ?? [];
      // Deterministic order: lex-smallest first. Keeps test fixtures
      // stable and matches pathBuilder's tiebreaker.
      const sorted = [...edges].sort((a, b) =>
        a[take].localeCompare(b[take]),
      );
      for (const e of sorted) {
        const neighbour = e[take];
        if (visited.has(neighbour)) continue;
        visited.add(neighbour);
        const node = nodeByKey.get(neighbour);
        if (node) {
          result.push(node);
          next.push(neighbour);
        }
      }
    }
    frontier = next;
  }
  return result;
}

function buildSearchIndex(nodes: GraphViewNode[]): SearchItem[] {
  const items: SearchItem[] = [];
  for (const n of nodes) {
    // Node itself
    items.push({
      kind: "node",
      label: n.title,
      haystack: (n.title + " " + (n.subtitle ?? "") + " " + n.kind).toLowerCase(),
      nodeKey: n.nodeKey,
    });
    // Variable / model projection (keeps the same nodeKey so commit
    // still goes to the producing node).
    if (isVariableNode(n)) {
      items.push({
        kind: "variable",
        label: n.title,
        haystack: n.title.toLowerCase(),
        nodeKey: n.nodeKey,
      });
    }
    if (isModelNode(n)) {
      items.push({
        kind: "model",
        label: n.title,
        haystack: n.title.toLowerCase(),
        nodeKey: n.nodeKey,
      });
    }
    // Decisions — each rendered as its own hit so search "logit" can
    // surface a model_type decision even if the node title is "Primary".
    for (const d of n.decisions) {
      items.push({
        kind: "decision",
        label: d.question,
        haystack: (d.question + " " + d.picked + " " + d.id).toLowerCase(),
        nodeKey: n.nodeKey,
        detail: d.id,
      });
    }
  }
  return items;
}

// ---------------------------------------------------------------------------
// V1.6.5 — Variable role grouping. Plan §8 / Phase D2.
//
// Buckets var->model role edges into ordered role groups for rendering.
// Roles live on the *edge* (op + params), never on the node, so a single
// column may appear under multiple roles (e.g. focal + cluster).
// ---------------------------------------------------------------------------

type RoleEdge = { source: string; target: string; op: string; params?: Record<string, unknown> };
export type RoleGroup = { role: Role; columns: string[]; dropped: Set<string> };

function columnOf(varNodeId: string): string {
  // "var:x1:cleaned" -> "x1"
  const m = /^var:(.+):cleaned$/.exec(varNodeId);
  return m ? m[1] : varNodeId;
}

export function groupVariablesByRole(edges: RoleEdge[], modelNodeId: string): RoleGroup[] {
  const byRole = new Map<Role, RoleGroup>();
  for (const e of edges) {
    if (e.target !== modelNodeId) continue;
    const role = ROLE_OF_EDGE_OP[e.op];
    if (!role) continue;
    const g = byRole.get(role) ?? { role, columns: [], dropped: new Set<string>() };
    const col = columnOf(e.source);
    if (!g.columns.includes(col)) g.columns.push(col);
    if (e.params?.dropped === true) g.dropped.add(col);
    byRole.set(role, g);
  }
  const order = [...ROLE_GROUP_ORDER, "explanatory_unspecified" as Role];
  return order.filter((r) => byRole.has(r)).map((r) => byRole.get(r)!);
}
