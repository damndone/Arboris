// Turn the ephemeral two-node diff into a node that survives a reload.
//
// The picked pair already produces a diff on screen, but that diff lives in
// React state: reload and the conclusion is gone. This asks the backend to
// store it, which projects a comparison node joining both endpoints into the
// forest. The backend re-derives every fact; all we send is which two nodes
// the user pointed at.

import { useState } from "react";
import { ApiError, createCompareNode } from "../../api";
import type { NodeOperationContextV1 } from "../api/nodeOperationContext";

function endpoint(context: NodeOperationContextV1): { runId: string; nodeId: string } | null {
  // A context may carry no candidate refs at all (legacy or partially
  // resolved). Returning null hides the button; reading through would crash
  // the whole drawer, which is a far worse answer to "can't compare this".
  const runId = context.ownership?.owner_run_id;
  const refs = context.ownership?.candidate_run_refs ?? [];
  const ref = refs.find((item) => item.run_id === runId);
  if (!runId || !ref?.op_node_id) return null;
  return { runId, nodeId: ref.op_node_id };
}

export function KeepComparisonButton({
  projectRoot,
  left,
  right,
  onKept,
}: {
  projectRoot: string | null | undefined;
  left: NodeOperationContextV1;
  right: NodeOperationContextV1;
  onKept: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const leftEndpoint = endpoint(left);
  const rightEndpoint = endpoint(right);
  if (!projectRoot || !leftEndpoint || !rightEndpoint) return null;

  async function keep() {
    if (!projectRoot || !leftEndpoint || !rightEndpoint) return;
    setBusy(true);
    setError(null);
    try {
      await createCompareNode(projectRoot, leftEndpoint, rightEndpoint);
      onKept();
    } catch (caught) {
      // The backend's refusal codes say which pairs cannot be compared and
      // why, so show that rather than a generic failure.
      setError(
        caught instanceof ApiError
          ? `${caught.code ?? "ERROR"}: ${caught.message}`
          : "Could not store this comparison.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <span>
      <button type="button" onClick={() => void keep()} disabled={busy} data-testid="keep-comparison">
        {busy ? "Keeping…" : "Keep as a node"}
      </button>
      {error && (
        <span
          role="alert"
          data-testid="keep-comparison-error"
          style={{ marginLeft: 8, fontSize: 12, color: "var(--danger, #f55)" }}
        >
          {error}
        </span>
      )}
    </span>
  );
}
