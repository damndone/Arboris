// frontend/src/workbench/ModelNodeBadge.tsx
//
// Show a readable run time; keep exact provenance in an expandable Source.

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
    <div
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
      <span>{/^\d{6}$/.test(runShort(runId)) ? runShort(runId).replace(/(..)(..)(..)/, "$1:$2:$3") : "Model version"}</span>
      <span aria-hidden>·</span>
      <span>{role}</span>
      <details onClick={event => event.stopPropagation()}><summary>Source</summary><div>Run: {runId}</div><div>Content: {nodeHash}</div></details>
    </div>
  );
}
