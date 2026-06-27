import type { NodeOperationContextV1 } from "../../api/nodeOperationContext";

export function buildAskAIContextPacket(context: NodeOperationContextV1) {
  return {
    packet_version: "ask-ai-context/v1" as const,
    source_context_version: context.context_version,
    context_fingerprint: context.context_fingerprint,
    packet_scope: {
      scope_type: "selected_node" as const,
      includes_upstream_path: true,
      includes_downstream_nodes: false,
      includes_full_run: false,
    },
    selection: context.selection,
    ownership: {
      active_head_run_id: context.ownership.active_head_run_id,
      owner_run_id: context.ownership.owner_run_id,
      owner_resolution: context.ownership.owner_resolution,
      shared_by_run_ids: context.ownership.shared_by_run_ids,
      candidate_run_ids: context.ownership.candidate_run_ids,
    },
    operation_target: context.operation_target,
    lineage_summary: context.lineage_context,
    node_summary: {
      params: context.node_payload.params,
      decisions: context.node_payload.decisions,
      editable_schema_summary: context.node_payload.editable_schema,
      metrics: context.node_payload.metrics,
      execution_diagnostics: context.node_payload.execution_diagnostics,
    },
    artifacts: context.node_payload.artifacts,
    context_diagnostics: context.context_diagnostics,
    context_visibility_notice: {
      artifact_policy: "metadata_and_safe_preview_only" as const,
      full_datasets_included: false as const,
      full_reports_included: false as const,
      binary_artifacts_included: false as const,
    },
    allowed_response_modes: [
      "explain",
      "summarize",
      "identify_risks",
      "suggest_questions",
    ] as const,
    response_guardrails: {
      advisory_text_only: true as const,
      executable_actions_allowed: false as const,
      graph_mutations_allowed: false as const,
      backend_payloads_allowed: false as const,
      file_reads_allowed: false as const,
      must_disclose_visibility_limits: true as const,
    },
  };
}

export type AskAIContextPacket = ReturnType<typeof buildAskAIContextPacket>;
