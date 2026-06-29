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

export interface CompareWithSourceResult {
  compare_version: "compare-with-source/v1";
  compare_kind: "source";
  left: NodeOperationContextV1;
  right: NodeOperationContextV1;
  provenance: {
    source_kind: "node_level_rerun_from" | "run_level_rerun_from_fallback";
    rerun_request_id: string;
    patch_id?: string;
  };
  sections: {
    params: CompareSection<FieldDiff>;
    decisions: CompareSection<FieldDiff>;
    metrics: CompareSection<FieldDiff>;
    diagnostics: CompareSection<FieldDiff>;
    artifacts: CompareSection<FieldDiff>;
    upstream_path: CompareSection<FieldDiff>;
  };
}

export function buildCompareWithSourceResult(input: {
  source: NodeOperationContextV1;
  current: NodeOperationContextV1;
  provenance: CompareWithSourceResult["provenance"];
}): CompareWithSourceResult {
  return {
    compare_version: "compare-with-source/v1",
    compare_kind: "source",
    left: input.source,
    right: input.current,
    provenance: input.provenance,
    sections: {
      params: fieldSection(
        "parameter",
        input.source.node_payload.params,
        input.current.node_payload.params,
        10,
      ),
      decisions: emptySection("No decision changes detected."),
      metrics: fieldSection(
        "metric",
        input.source.node_payload.metrics ?? {},
        input.current.node_payload.metrics ?? {},
        10,
      ),
      diagnostics: emptySection("No diagnostic changes detected."),
      artifacts: emptySection("No artifact summary changes detected."),
      upstream_path: upstreamPathSection(input.source, input.current),
    },
  };
}

function emptySection<T>(summary: string): CompareSection<T> {
  return { changed: false, total_changed: 0, items: [], summary };
}

function fieldSection(
  label: string,
  left: Record<string, unknown>,
  right: Record<string, unknown>,
  limit: number,
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
  return {
    changed: diffs.length > 0,
    total_changed: diffs.length,
    items: diffs.slice(0, limit),
    truncated: diffs.length > limit || undefined,
    summary:
      diffs.length === 0
        ? `No ${label} changes detected.`
        : `${diffs.length} ${label} changes detected.`,
  };
}

function upstreamPathSection(
  source: NodeOperationContextV1,
  current: NodeOperationContextV1,
): CompareSection<FieldDiff> {
  const oldPath = source.lineage_context.upstream_path.map((node) => node.key);
  const newPath = current.lineage_context.upstream_path.map((node) => node.key);
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

function stableValue(value: unknown): string {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return JSON.stringify(value, Object.keys(value as Record<string, unknown>).sort());
  }
  return JSON.stringify(value);
}
