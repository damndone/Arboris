// Shared diff engine for lineage-node comparison (v1.6.11 slice B).
//
// One set of section builders, used by both `compareWithSource` (a node vs its
// rerun source) and `compareNodes` (any two nodes on the forest). Keeping the
// primitives here means the two comparison surfaces can never drift in how they
// compute a diff.

import type { NodeOperationContextV1 } from "./nodeOperationContext";

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

/** Diff two flat records (params, metrics). Numeric fields carry a signed delta. */
export function recordSection(
  label: string,
  left: Record<string, unknown>,
  right: Record<string, unknown>,
  limit: number = DEFAULT_SECTION_LIMIT,
): CompareSection<FieldDiff> {
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
  return {
    changed: true,
    total_changed: 1,
    items: [
      {
        field_id: "upstream_path",
        change_type: "changed",
        old_value: oldPath,
        new_value: newPath,
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
