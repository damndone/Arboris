import type { ResolveNodeOperationContextResult } from "../api/nodeOperationContext";

type FailureResult = Exclude<ResolveNodeOperationContextResult, { ok: true }>;

export function ResolverFailureState({ result }: { result: FailureResult }) {
  return (
    <div
      data-testid="resolver-failure-state"
      role="status"
      style={{
        fontSize: 12,
        color: "var(--label-secondary)",
        lineHeight: 1.4,
      }}
    >
      <strong>Node context needs clarification</strong>
      <div>{result.reason}</div>
      {result.candidate_run_refs && result.candidate_run_refs.length > 0 && (
        <div>
          Candidate runs:{" "}
          {result.candidate_run_refs.map((ref) => ref.run_id).join(", ")}
        </div>
      )}
    </div>
  );
}
