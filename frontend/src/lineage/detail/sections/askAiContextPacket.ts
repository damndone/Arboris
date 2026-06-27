import type { NodeOperationContextV1 } from "../../api/nodeOperationContext";

type ContextArtifact = NodeOperationContextV1["node_payload"]["artifacts"][number];

const MAX_ARTIFACT_TEXT_CHARS = 2_000;
const MAX_ARTIFACT_ARRAY_ITEMS = 20;
const MAX_ARTIFACT_OBJECT_KEYS = 50;
const TRUNCATION_SUFFIX = "...[truncated]";

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
    artifacts: context.node_payload.artifacts.map(sanitizeArtifactForAskAI),
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

function sanitizeArtifactForAskAI(artifact: ContextArtifact) {
  const safeArtifact: {
    name: ContextArtifact["name"];
    mime: ContextArtifact["mime"];
    sizeBytes?: ContextArtifact["sizeBytes"];
    sha256?: ContextArtifact["sha256"];
    ai_visibility: ContextArtifact["ai_visibility"];
    summary?: unknown;
    preview?: unknown;
    redactions?: unknown;
  } = {
    name: artifact.name,
    mime: artifact.mime,
    ai_visibility: artifact.ai_visibility,
  };
  const redactions = new Set<string>(
    Array.isArray((artifact as { redactions?: unknown }).redactions)
      ? ((artifact as { redactions?: unknown[] }).redactions ?? [])
          .filter((item): item is string => typeof item === "string")
      : [],
  );

  if (artifact.sizeBytes !== undefined) safeArtifact.sizeBytes = artifact.sizeBytes;
  if (artifact.sha256 !== undefined) safeArtifact.sha256 = artifact.sha256;

  const extendedArtifact = artifact as ContextArtifact & {
    summary?: unknown;
    preview?: unknown;
    redactions?: unknown;
  };
  if (extendedArtifact.summary !== undefined) {
    const sanitized = sanitizePreviewValue(extendedArtifact.summary);
    safeArtifact.summary = sanitized.value;
    if (sanitized.truncated) redactions.add("ask_ai_summary_truncated");
  }
  if (extendedArtifact.preview !== undefined) {
    if (allowsArtifactPreview(artifact.mime)) {
      const sanitized = sanitizePreviewValue(extendedArtifact.preview);
      safeArtifact.preview = sanitized.value;
      if (sanitized.truncated) redactions.add("ask_ai_preview_truncated");
    } else {
      redactions.add("ask_ai_preview_omitted_for_mime");
    }
  }
  if (redactions.size > 0) safeArtifact.redactions = [...redactions];

  return safeArtifact;
}

function allowsArtifactPreview(mime: string): boolean {
  const normalized = mime.toLowerCase();
  if (
    normalized.startsWith("image/") ||
    normalized.startsWith("audio/") ||
    normalized.startsWith("video/")
  ) {
    return false;
  }
  return ![
    "application/pdf",
    "application/octet-stream",
    "application/zip",
    "application/x-parquet",
  ].includes(normalized);
}

function sanitizePreviewValue(value: unknown): { value: unknown; truncated: boolean } {
  if (typeof value === "string") {
    if (value.length <= MAX_ARTIFACT_TEXT_CHARS) {
      return { value, truncated: false };
    }
    return {
      value: `${value.slice(0, MAX_ARTIFACT_TEXT_CHARS)}${TRUNCATION_SUFFIX}`,
      truncated: true,
    };
  }
  if (Array.isArray(value)) {
    let truncated = value.length > MAX_ARTIFACT_ARRAY_ITEMS;
    const items = value
      .slice(0, MAX_ARTIFACT_ARRAY_ITEMS)
      .map((item) => {
        const sanitized = sanitizePreviewValue(item);
        if (sanitized.truncated) truncated = true;
        return sanitized.value;
      });
    return { value: items, truncated };
  }
  if (value && typeof value === "object") {
    const entries = Object.entries(value);
    let truncated = entries.length > MAX_ARTIFACT_OBJECT_KEYS;
    const output: Record<string, unknown> = {};
    for (const [key, child] of entries.slice(0, MAX_ARTIFACT_OBJECT_KEYS)) {
      const sanitized = sanitizePreviewValue(child);
      if (sanitized.truncated) truncated = true;
      output[key] = sanitized.value;
    }
    return { value: output, truncated };
  }
  return { value, truncated: false };
}
