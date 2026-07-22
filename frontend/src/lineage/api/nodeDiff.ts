// Shared diff engine for lineage-node comparison (v1.6.11 slice B).
//
// One set of section builders, used by both `compareWithSource` (a node vs its
// rerun source) and `compareNodes` (any two nodes on the forest). Keeping the
// primitives here means the two comparison surfaces can never drift in how they
// compute a diff.

import type { NodeOperationContextV1 } from "./nodeOperationContext";
import { formatUpstreamPath } from "./pathFormat";

export interface CompareSection<T> {
  changed: boolean;
  total_changed: number;
  items: T[];
  truncated?: boolean;
  summary: string;
}

export interface FieldDiff {
  field_id: string;
  label?: string;
  change_type: "added" | "removed" | "changed";
  old_value?: unknown;
  new_value?: unknown;
  delta?: number | string | null;
}

export const DEFAULT_SECTION_LIMIT = 10;

export function emptySection<T>(summary: string): CompareSection<T> {
  return { changed: false, total_changed: 0, items: [], summary };
}

const MAX_FLATTEN_DEPTH = 6;

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * Expand nested objects into dotted leaf paths so a diff lands on the field
 * that actually changed.
 *
 * A model node carries its whole configuration under a single `model_options`
 * key. Diffed as one value, any edit rendered as two ~900-character JSON blobs
 * joined by an arrow, and the reader had to spot the changed keys by eye. Leaf
 * paths also make the reported change count mean something: switching a mean
 * model reads as the handful of orders and modes it really touched.
 *
 * Arrays stay whole — index-wise diffs of an order vector are noisier than the
 * vector itself.
 */
export function flattenRecord(
  record: Record<string, unknown>,
  prefix = "",
  depth = 0,
): Record<string, unknown> {
  const flat: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(record)) {
    const path = prefix ? `${prefix}.${key}` : key;
    if (isPlainObject(value) && depth < MAX_FLATTEN_DEPTH) {
      const nested = flattenRecord(value, path, depth + 1);
      // An empty object is itself the value; keep it visible rather than drop it.
      if (Object.keys(nested).length === 0) flat[path] = value;
      else Object.assign(flat, nested);
    } else {
      flat[path] = value;
    }
  }
  return flat;
}

/** Diff two records (params, metrics), expanding nested objects to leaf paths. */
export function recordSection(
  label: string,
  leftRaw: Record<string, unknown>,
  rightRaw: Record<string, unknown>,
  limit: number = DEFAULT_SECTION_LIMIT,
): CompareSection<FieldDiff> {
  const left = flattenRecord(leftRaw);
  const right = flattenRecord(rightRaw);
  const keys = Array.from(new Set([...Object.keys(left), ...Object.keys(right)])).sort();
  const diffs = keys.flatMap((key): FieldDiff[] => {
    if (!(key in left)) {
      return [{ field_id: key, change_type: "added", new_value: right[key] }];
    }
    if (!(key in right)) {
      return [{ field_id: key, change_type: "removed", old_value: left[key] }];
    }
    if (stableValue(left[key]) === stableValue(right[key])) return [];
    const delta =
      typeof left[key] === "number" && typeof right[key] === "number"
        ? (right[key] as number) - (left[key] as number)
        : null;
    return [
      {
        field_id: key,
        change_type: "changed",
        old_value: left[key],
        new_value: right[key],
        delta,
      },
    ];
  });
  return sectionFromDiffs(diffs, label, limit);
}

type Decision = NodeOperationContextV1["node_payload"]["decisions"][number];

/** Diff decisions by id, surfacing changes to the picked option or review status. */
export function decisionSection(
  left: readonly Decision[],
  right: readonly Decision[],
  limit: number = DEFAULT_SECTION_LIMIT,
): CompareSection<FieldDiff> {
  const leftById = new Map(left.map((d) => [d.id, d]));
  const rightById = new Map(right.map((d) => [d.id, d]));
  const ids = Array.from(new Set([...leftById.keys(), ...rightById.keys()])).sort();
  const diffs = ids.flatMap((id): FieldDiff[] => {
    const l = leftById.get(id);
    const r = rightById.get(id);
    if (!l) return [{ field_id: id, label: r?.question, change_type: "added", new_value: decisionValue(r!) }];
    if (!r) return [{ field_id: id, label: l.question, change_type: "removed", old_value: decisionValue(l) }];
    if (stableValue(decisionValue(l)) === stableValue(decisionValue(r))) return [];
    return [
      {
        field_id: id,
        label: l.question,
        change_type: "changed",
        old_value: decisionValue(l),
        new_value: decisionValue(r),
      },
    ];
  });
  return sectionFromDiffs(diffs, "decision", limit);
}

function decisionValue(decision: Decision): { picked: string; reviewStatus: string } {
  return { picked: decision.picked, reviewStatus: decision.reviewStatus };
}

type Diagnostic = { level: string; message: string };

/** Diff execution diagnostics as a set of `level: message` entries. */
export function diagnosticsSection(
  left: readonly Diagnostic[] | undefined,
  right: readonly Diagnostic[] | undefined,
  limit: number = DEFAULT_SECTION_LIMIT,
): CompareSection<FieldDiff> {
  const leftKeys = new Map((left ?? []).map((d) => [diagnosticKey(d), d]));
  const rightKeys = new Map((right ?? []).map((d) => [diagnosticKey(d), d]));
  const keys = Array.from(new Set([...leftKeys.keys(), ...rightKeys.keys()])).sort();
  const diffs = keys.flatMap((key): FieldDiff[] => {
    const l = leftKeys.get(key);
    const r = rightKeys.get(key);
    if (l && r) return [];
    if (r) return [{ field_id: key, label: r.level, change_type: "added", new_value: r.message }];
    return [{ field_id: key, label: l!.level, change_type: "removed", old_value: l!.message }];
  });
  return sectionFromDiffs(diffs, "diagnostic", limit);
}

function diagnosticKey(d: Diagnostic): string {
  return `${d.level}: ${d.message}`;
}

/** Diff the upstream lineage path (ordered node keys). */
export function upstreamPathSection(
  left: NodeOperationContextV1,
  right: NodeOperationContextV1,
): CompareSection<FieldDiff> {
  const oldPath = left.lineage_context.upstream_path.map((node) => node.key);
  const newPath = right.lineage_context.upstream_path.map((node) => node.key);
  if (stableValue(oldPath) === stableValue(newPath)) {
    return emptySection("No upstream path changes detected.");
  }
  // Equality is judged on keys (identity), but the rendered values are the
  // human labels — a diff of bare hash::id keys is unreadable in the drawer.
  // DAG-aware: parallel same-depth nodes group as "(a + b)" not "a → b".
  const labelPath = (ctx: NodeOperationContextV1) =>
    formatUpstreamPath(
      ctx.lineage_context.upstream_path.map((node) => ({
        label: node.label || node.key,
        depth: node.depth,
      })),
    );
  return {
    changed: true,
    total_changed: 1,
    items: [
      {
        field_id: "upstream_path",
        label: "Upstream path",
        change_type: "changed",
        old_value: labelPath(left),
        new_value: labelPath(right),
      },
    ],
    summary: "Upstream path changed.",
  };
}

function sectionFromDiffs(
  diffs: FieldDiff[],
  label: string,
  limit: number,
): CompareSection<FieldDiff> {
  return {
    changed: diffs.length > 0,
    total_changed: diffs.length,
    items: diffs.slice(0, limit),
    truncated: diffs.length > limit || undefined,
    summary:
      diffs.length === 0
        ? `No ${label} changes detected.`
        : `${diffs.length} ${label} change${diffs.length === 1 ? "" : "s"} detected.`,
  };
}

export function stableValue(value: unknown): string {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return JSON.stringify(value, Object.keys(value as Record<string, unknown>).sort());
  }
  return JSON.stringify(value);
}
