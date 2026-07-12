// v1.6.11 — honest DAG-aware path formatting.
//
// upstream_path is a flat topological order; nodes sharing a `depth` are
// PARALLEL branches (e.g. wage/education/exper fanning out of the cleaned
// dataset). Joining everything with "→" misrepresented them as sequential
// (user report 2026-07-12): parallel nodes join with " + " inside parens.

export interface PathItemLike {
  label: string;
  depth?: number;
}

/** "Raw → Cleaned → (wage + education + exper) → model". Items without a
 *  depth (legacy contexts) degrade to the old plain arrow chain. */
export function formatUpstreamPath(items: PathItemLike[]): string {
  return groupByDepth(items)
    .map((group) =>
      group.length === 1
        ? group[0].label
        : `(${group.map((item) => item.label).join(" + ")})`,
    )
    .join(" → ");
}

/** Consecutive same-depth runs (undefined depth never groups). */
export function groupByDepth<T extends PathItemLike>(items: T[]): T[][] {
  const groups: T[][] = [];
  for (const item of items) {
    const last = groups[groups.length - 1];
    if (
      last &&
      item.depth !== undefined &&
      last[0].depth !== undefined &&
      last[0].depth === item.depth
    ) {
      last.push(item);
    } else {
      groups.push([item]);
    }
  }
  return groups;
}

/** Separator to render BETWEEN adjacent items: "+" for parallel siblings,
 *  "→" for a real dependency step. Only needs `depth`. */
export function separatorAfter(
  items: Array<{ depth?: number }>,
  index: number,
): "+" | "→" {
  const current = items[index];
  const next = items[index + 1];
  if (
    current?.depth !== undefined &&
    next?.depth !== undefined &&
    current.depth === next.depth
  ) {
    return "+";
  }
  return "→";
}
