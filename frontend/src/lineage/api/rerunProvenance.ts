import type {
  NodeOperationContextV1,
  RerunFromProvenance,
} from "./nodeOperationContext";

export type CompareWithSourceGate =
  | {
      ok: true;
      source_kind: "node_level_rerun_from" | "run_level_rerun_from_fallback";
      rerun_from: RerunFromProvenance;
    }
  | {
      ok: false;
      reason:
        | "missing_rerun_from"
        | "provenance_mismatch"
        | "run_level_fallback_ambiguous";
    };

export function getCompareWithSourceGate(
  context: NodeOperationContextV1,
): CompareWithSourceGate {
  if (context.rerun_from) {
    if (
      context.run_rerun_from &&
      !sameRerunFrom(context.rerun_from, context.run_rerun_from)
    ) {
      return { ok: false, reason: "provenance_mismatch" };
    }
    return {
      ok: true,
      source_kind: "node_level_rerun_from",
      rerun_from: context.rerun_from,
    };
  }
  if (
    context.run_rerun_from &&
    context.ownership.candidate_run_ids.length === 1
  ) {
    return {
      ok: true,
      source_kind: "run_level_rerun_from_fallback",
      rerun_from: context.run_rerun_from,
    };
  }
  return {
    ok: false,
    reason: context.run_rerun_from
      ? "run_level_fallback_ambiguous"
      : "missing_rerun_from",
  };
}

function sameRerunFrom(
  left: RerunFromProvenance,
  right: RerunFromProvenance,
): boolean {
  return (
    left.owner_run_id === right.owner_run_id &&
    left.op_node_id === right.op_node_id &&
    left.node_hash === right.node_hash &&
    left.context_fingerprint === right.context_fingerprint &&
    left.rerun_request_id === right.rerun_request_id &&
    (left.patch_id ?? null) === (right.patch_id ?? null)
  );
}
