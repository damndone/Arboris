// frontend/src/workbench/views/ForestRouteView.tsx
//
// v1.6.1 (2C.6) — self-contained forest route (gated by ?forest=1).
//
// Owns its own head-set data load + ForestCanvas render, deliberately bypassing
// the per-run GraphCanvas machinery (selection drawer, search, dagre). Editing a
// model node forks a sibling branch in place; `onRerun` refetches the head-set so
// the new head appears without navigation. A legacy target (no node identity)
// degrades to a notice rather than crashing.

import { useForestData } from "../../lineage/hooks/useForestData";
import { ForestCanvas } from "../../lineage/graph/ForestCanvas";

export function ForestRouteView({
  projectRoot,
  runId,
}: {
  projectRoot: string;
  runId: string;
}) {
  const { forest, loading, error, refetch } = useForestData(projectRoot, runId);

  if (loading || forest === null) {
    if (error) {
      return (
        <div data-testid="forest-error" role="alert" style={{ padding: 24 }}>
          Failed to load lineage forest{error.detail ? `: ${error.detail}` : ""}.
        </div>
      );
    }
    return (
      <div data-testid="forest-loading" style={{ padding: 24, color: "var(--label-secondary)" }}>
        Loading lineage forest…
      </div>
    );
  }

  if (forest.legacy) {
    return (
      <div data-testid="forest-legacy" style={{ padding: 24, color: "var(--label-secondary)" }}>
        This run predates cross-run lineage. Re-run to populate the forest.
      </div>
    );
  }

  return (
    <div data-testid="forest-route" data-view="forest" style={{ flex: 1, minHeight: 0, padding: 12 }}>
      <ForestCanvas
        forest={forest}
        projectRoot={projectRoot}
        runId={runId}
        onRerun={() => refetch()}
      />
    </div>
  );
}
