// frontend/src/workbench/ModelNodeBadge.tsx
//
// V1.6.5 — Problem 6: distinguish same-named model nodes across the forest
// (Plan §8 / Phase F1). Two reruns both labelled "ols_robust (primary)" are
// otherwise indistinguishable. This badge stamps each forest model node with a
// stable identity: `…<run-short> · #<hash-short> · <role>` where
//   - run-short  = the HHMMSS segment of the run id (stable, human-skimmable)
//   - hash-short = first 5 chars of the node hash (content identity)
//   - role       = "source" for the originating run, "rerun" for children.

/** Extract the HHMMSS time segment from a run id like
 *  "20260630_021506_881210_d5cbd8a7". Falls back to the whole id when the
 *  shape is unexpected so the badge never renders empty. */
export function runShort(runId: string): string {
  const parts = runId.split("_");
  return parts.length >= 2 ? parts[1] : runId;
}

export function hashShort(nodeHash: string): string {
  return nodeHash.slice(0, 5);
}

export function ModelNodeBadge({
  runId,
  nodeHash,
  role,
}: {
  runId: string;
  nodeHash: string;
  role: "source" | "rerun";
}) {
  return (
    <span
      data-testid="model-node-badge"
      data-role={role}
      style={{
        display: "inline-flex",
        gap: 4,
        alignItems: "center",
        fontSize: 10,
        fontFamily: "var(--font-mono)",
        color: "var(--label-tertiary)",
      }}
    >
      <span>…{runShort(runId)}</span>
      <span aria-hidden>·</span>
      <span>#{hashShort(nodeHash)}</span>
      <span aria-hidden>·</span>
      <span>{role}</span>
    </span>
  );
}
