// frontend/src/workbench/views/tableRunScope.ts
//
// Which runs the Table view reads.
//
// Table used to be pinned to a single run (`forest.activeRunId ?? model.runId`).
// That made results look like they had been lost: a statistical exploration is
// saved against its SOURCE run, so as soon as the active head moved to a newer
// run the Table showed that run's (empty) artifact set and the exploration
// appeared to vanish. Nothing was cached and nothing was deleted — the view was
// simply looking somewhere else.
//
// Scope rule:
//   - a node is selected  → its whole lineage chain (the node's owning run plus
//                           every `rerunOf` ancestor), newest run first;
//   - nothing selected    → every run in the project forest, newest first.

import type { ForestViewModel } from "../../lineage/api/graphViewTypes";

export interface TableRunScopeInput {
  forest: ForestViewModel | null | undefined;
  activeRunId: string | null | undefined;
  selectedKey: string | null | undefined;
  /** The URL/legacy run, used when there is no forest to reason about. */
  fallbackRunId: string;
}

function byNewestFirst(
  runIds: readonly string[],
  createdAt: ReadonlyMap<string, string>,
): string[] {
  return [...runIds].sort((a, b) => {
    const left = createdAt.get(a) ?? "";
    const right = createdAt.get(b) ?? "";
    if (left === right) return b.localeCompare(a);
    return right.localeCompare(left);
  });
}

/** The run that owns a (possibly deduplicated) node.
 *
 *  A node shared across runs has no single owner, so anchor on the run the user
 *  is looking at when it is one of them — the same rule the rerun path uses. */
function ownerRunOf(
  runs: readonly string[],
  activeRunId: string | null | undefined,
): string | null {
  if (runs.length === 0) return null;
  if (activeRunId && runs.includes(activeRunId)) return activeRunId;
  return runs[0] ?? null;
}

export function resolveTableRunScope({
  forest,
  activeRunId,
  selectedKey,
  fallbackRunId,
}: TableRunScopeInput): string[] {
  if (!forest) return fallbackRunId ? [fallbackRunId] : [];

  const createdAt = new Map<string, string>();
  const parentOf = new Map<string, string | null>();
  for (const head of forest.heads ?? []) {
    if (!head?.runId) continue;
    createdAt.set(head.runId, head.createdAt ?? "");
    parentOf.set(head.runId, head.rerunOf ?? null);
  }

  const selectedNode = selectedKey
    ? (forest.nodes ?? []).find((node) => node.nodeKey === selectedKey)
    : undefined;

  if (!selectedNode) {
    const all = [...parentOf.keys()];
    if (all.length === 0) return fallbackRunId ? [fallbackRunId] : [];
    return byNewestFirst(all, createdAt);
  }

  const owner = ownerRunOf(selectedNode.runs ?? [], activeRunId);
  if (!owner) return fallbackRunId ? [fallbackRunId] : [];

  // Walk to the chain root. `seen` is not defensive decoration: a malformed or
  // hand-edited head set with a rerunOf cycle would otherwise hang the view.
  const chain: string[] = [];
  const seen = new Set<string>();
  let current: string | null | undefined = owner;
  while (current && !seen.has(current)) {
    seen.add(current);
    chain.push(current);
    current = parentOf.get(current) ?? null;
  }
  return byNewestFirst(chain, createdAt);
}
