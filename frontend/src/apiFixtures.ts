/** Test fixtures that satisfy the generated API types (apiTypes.ts). */
import type { Schema } from "./apiTypes";

/** A complete, minimal run detail; override only what a test is about. */
export function runDetailFixture(overrides: Partial<Schema<"RunDetail">> = {}): Schema<"RunDetail"> {
  return {
    run_id: "run_fixture",
    status: "completed",
    mode: "auto",
    started_at: null,
    y: null,
    x: null,
    lineage: [],
    artifact_counts: {},
    errors: { issues: [] },
    model_results: [],
    diagnostic_summary_preview: {
      available: false,
      preview_contract_version: "fixture",
      source_schema_version: "fixture",
      preview_status: "unavailable",
      contract_warnings: [],
      run_lifecycle_status: "completed",
      trust_label: "legacy_unavailable",
      primary_reasons: [],
    },
    table_1: [],
    statistical_evidence: null,
    labels: {},
    term_labels: {},
    model_family_evidence: null,
    family_evidence: null,
    prediction_evidence: null,
    post_estimation_results: [],
    post_estimation_results_total: 0,
    ...overrides,
  };
}

type DraftNode = Schema<"DraftGraph">["nodes"][number];

export function draftSourceRefFixture(overrides: Partial<Schema<"DraftSourceRef">> = {}): Schema<"DraftSourceRef"> {
  return {
    source_run_id: "run_a",
    source_model_node_id: "model:ols_1",
    source_op_node_id: "model:ols_1",
    source_node_hash: "hash_model",
    source_context_fingerprint: "ctx_fixture",
    ...overrides,
  };
}

export function runCreatedFromFixture(overrides: Partial<Schema<"RunCreatedFrom">> = {}): Schema<"RunCreatedFrom"> {
  return {
    source_type: "run",
    source_run_id: "run_a",
    source_model_node_id: "model:ols_1",
    source_op_node_id: "model:ols_1",
    source_node_hash: "hash_model",
    source_context_fingerprint: "ctx_fixture",
    source_input_fingerprint: "input_fixture",
    ...overrides,
  };
}

export function uploadDraftNodeFixture(overrides: Partial<Schema<"UploadDraftNode">> = {}): Schema<"UploadDraftNode"> {
  return {
    node_id: "source_1",
    node_type: "input.upload",
    upload: { sha256: "sha_fixture", filename: "data.csv" },
    sheet_names: [],
    status: "bound",
    ...overrides,
  };
}

export function tableDraftNodeFixture(overrides: Partial<Schema<"TableDraftNode">> = {}): Schema<"TableDraftNode"> {
  return {
    node_id: "table_1",
    node_type: "table",
    params: { sheet_name: null, transpose: false },
    columns: [],
    status: "pending",
    ...overrides,
  };
}

export function inputDatasetDraftNodeFixture(
  overrides: Partial<Schema<"InputDatasetDraftNode">> = {},
): Schema<"InputDatasetDraftNode"> {
  return {
    node_id: "input_1",
    node_type: "input.dataset",
    source_type: "run_input",
    run_input_id: "run_a",
    schema_fingerprint: "schema_fixture",
    input_fingerprint: "input_fixture",
    columns_summary: [],
    status: "bound",
    ...overrides,
  };
}

export function modelDraftNodeFixture(overrides: Partial<Schema<"ModelDraftNode">> = {}): Schema<"ModelDraftNode"> {
  return {
    node_id: "model_1",
    node_type: "model",
    model_family: "regression",
    model_type: "ols",
    schema_id: "ols@v1",
    editable_schema: [],
    params: {},
    ...overrides,
  };
}

/** A complete genesis draft (upload -> table -> model); override what matters. */
export function draftFixture(overrides: Partial<Schema<"PipelineDraft">> = {}): Schema<"PipelineDraft"> {
  const nodes: DraftNode[] = [uploadDraftNodeFixture(), tableDraftNodeFixture(), modelDraftNodeFixture()];
  return {
    draft_id: "draft_fixture",
    schema_version: "pipeline_draft.v1",
    created_at: "2026-10-07T00:00:00Z",
    updated_at: "2026-10-07T00:00:00Z",
    status: "draft",
    created_from: { source_type: "genesis", source_input_fingerprint: "input_fixture" },
    graph: {
      nodes,
      edges: [
        { from: "source_1", to: "table_1" },
        { from: "table_1", to: "model_1" },
      ],
    },
    default_execution_mode: "genesis",
    ...overrides,
  };
}

export function draftSummaryFixture(
  overrides: Partial<Schema<"PipelineDraftSummary">> = {},
): Schema<"PipelineDraftSummary"> {
  return {
    draft_id: "draft_fixture",
    status: "draft",
    model_type: "ols",
    source_run_id: null,
    source_model_node_id: null,
    source_op_node_id: null,
    source_node_hash: null,
    draft_hash: "hash_fixture",
    updated_at: null,
    ...overrides,
  };
}

/** A complete capability catalog with no models; override what a test needs. */
export function capabilitiesFixture(overrides: Partial<Schema<"Capabilities">> = {}): Schema<"Capabilities"> {
  return {
    schema_version: 3,
    editable_stages: ["model"],
    model_types: [],
    imputation_methods: [],
    prediction_models: [],
    sampling_methods: [],
    covariance_options: [],
    survey_design: {
      variance_methods: [],
      variance_method_requirements: {},
      replicate_types: [],
      lonely_psu_policies: [],
      df_conventions: [],
      design_fields: [],
      sampling_weight_families: [],
    },
    ...overrides,
  };
}

/** An Agent transcript entry; the server always sends every field. */
export function agentMessageFixture(
  message: Pick<Schema<"AgentMessage">, "entry_id" | "role" | "content"> & Partial<Schema<"AgentMessage">>,
): Schema<"AgentMessage"> {
  return { at: "2026-10-14T09:00:00+00:00", name: null, stop_reason: null, error: null, navigation: [], ...message };
}

/** An Agent proposal revision; `readable` is what the server derives from `changes`. */
export function agentProposalFixture(
  proposal: Omit<Schema<"PublicProposal">, "readable"> & Partial<Pick<Schema<"PublicProposal">, "readable">>,
): Schema<"PublicProposal"> {
  return { readable: [], ...proposal };
}

/** A provider model entry. */
export function llmModelFixture(
  model: Omit<Schema<"ProviderModel">, "supports_vision"> & Partial<Pick<Schema<"ProviderModel">, "supports_vision">>,
): Schema<"ProviderModel"> {
  return { supports_vision: false, ...model };
}

/** One registered Agent operation as the capability catalog lists it. */
export function operationCapabilityFixture(
  overrides: Partial<Schema<"OperationCapability">> = {},
): Schema<"OperationCapability"> {
  return {
    operation_id: "graph.fork",
    operation_version: "v1",
    effect_level: "mutation",
    scope: "current chain/node",
    scope_requirements: [],
    risk_level: "mutating",
    risk_authorization_policy: "none",
    confirmation_policy: "required",
    ui_description: "",
    example_prompts: [],
    natural_language_enabled: true,
    executor: "fixture",
    diff_builder: "fixture",
    reconciler: "fixture",
    verification_builder: "fixture",
    editable_schema: {},
    proposal_schema: {},
    ...overrides,
  };
}

/** The Agent capability catalog with nothing registered; override what a test needs. */
export function agentCapabilitiesFixture(
  overrides: Partial<Schema<"AgentCapabilities">> = {},
): Schema<"AgentCapabilities"> {
  return {
    capabilities: [],
    boundary: { advisory: [], unsupported: [] },
    control_plane_mode: "local",
    project_root: "/proj",
    scope: null,
    workers: 1,
    ...overrides,
  };
}

/** A /llm/chat reply. */
export function chatReplyFixture(
  reply: Partial<Schema<"ChatReply">> & Pick<Schema<"ChatReply">, "text">,
): Schema<"ChatReply"> {
  return { model: "fixture-model", context_fingerprint: null, ...reply };
}

/** A per-run graph node; override what a test is about. */
export function graphNodeFixture(
  node: Pick<Schema<"GraphNodeView">, "id" | "kind"> & Partial<Schema<"GraphNodeView">>,
): Schema<"GraphNodeView"> {
  return {
    display_label: node.id,
    summary: null,
    created_at: "",
    parent_stage_id: null,
    branch_id: "main",
    trust: "ok",
    trust_reason: null,
    archived: false,
    payload_ref: null,
    decision_points: [],
    annotations: [],
    stage: null,
    node_hash: null,
    ...node,
  };
}

/** A head-set / forest node shared by the runs in `runs`. */
export function forestNodeFixture(
  node: Pick<Schema<"ForestNodeView">, "id" | "kind"> & Partial<Schema<"ForestNodeView">>,
): Schema<"ForestNodeView"> {
  return {
    ...graphNodeFixture(node),
    producing_stage: null,
    cas_ref: null,
    runs: [],
    presentation_created_at: "",
    ...node,
  };
}

/** A forest edge. */
export function forestEdgeFixture(
  edge: Pick<Schema<"ForestEdge">, "source" | "target"> & Partial<Schema<"ForestEdge">>,
): Schema<"ForestEdge"> {
  return { op: null, params: null, ...edge };
}

/** A forest head (one run's leaf). */
export function forestHeadFixture(
  head: Pick<Schema<"ForestHead">, "run_id"> & Partial<Schema<"ForestHead">>,
): Schema<"ForestHead"> {
  return {
    head_node_hash: null,
    from_node: null,
    rerun_of: null,
    rerun_from: null,
    rerun_reason: null,
    status: null,
    created_at: null,
    ...head,
  };
}

/** The result of rejecting a memory candidate. */
export function candidateRejectedFixture(candidateId = "candidate-fixture", revision = 1): Schema<"CandidateRejected"> {
  return { review: { candidate_id: candidateId, revision, status: "rejected" }, automatic_execution: false };
}

const memoryScopeFixture: Schema<"MemoryScope"> = {
  namespace_id: "ns",
  profile_id: "profile",
  owner_id: "local-user",
  organization_id: null,
  visibility_scope: "private",
  promotion_scope: "user",
};

/** The result of approving a memory candidate: its content, approval and validity. */
export function memoryReviewedFixture(memoryId = "memory-fixture"): Schema<"MemoryReviewed"> {
  return {
    content: {
      contract_version: "domain-memory-content/v1",
      memory_id: memoryId,
      revision: 1,
      content_hash: "a".repeat(64),
      scope: memoryScopeFixture,
      domain_tags: [],
      memory_kind: "workflow_lesson",
      applicability_predicates: [],
      compact_lesson: "",
      recommended_effect_kind: "assumption_check_hint",
      recommended_target_refs: [],
      source_summary_refs: [],
      evidence_status: "observed_once",
      review_after: "2030-01-01T00:00:00Z",
      supersedes_revision: null,
      conflicts_with: [],
      created_by: "local-user",
      expires_at: null,
      apply_mode: "inform_only",
      vocabulary_version: null,
      verifier: null,
      last_validated_at: null,
    },
    approval: {
      contract_version: "domain-memory-approval/v1",
      approval_ref: "approval-fixture",
      memory_id: memoryId,
      content_revision: 1,
      content_hash: "a".repeat(64),
      scope: memoryScopeFixture,
      approver_id: "local-user",
      approved_at: "2026-10-07T00:00:00Z",
      expected_current_approval_ref: null,
      supersedes_approval_ref: null,
      grant_control_sequence: 1,
    },
    validity: {
      contract_version: "domain-memory-validity/v1",
      approval_ref: "approval-fixture",
      memory_id: memoryId,
      content_revision: 1,
      validity_revision: 1,
      control_sequence: 1,
      state: "active",
      effective_at: "2026-10-07T00:00:00Z",
      reason: "approved",
      authority: "local-user",
      evidence_refs: [],
    },
    automatic_execution: false,
  };
}

/** A notebook record; override what a test is about. */
export function notebookViewFixture(
  notebook: Pick<Schema<"NotebookView">, "notebook_id"> & Partial<Schema<"NotebookView">>,
): Schema<"NotebookView"> {
  return {
    record_type: "notebook",
    schema_version: "1.0",
    project_id: "project_fixture",
    run_family_id: "family_fixture",
    title: "Analysis",
    created_by: "user",
    created_at: "2026-10-07T00:00:00Z",
    active_head_run_id: null,
    focused_run_id: null,
    last_attempt_run_id: null,
    analysis_contract: {},
    user_focus: {},
    available_capabilities: [],
    projection_key: null,
    projection_source: null,
    supersedes_notebook_id: null,
    ...notebook,
  };
}

/** A notebook projection (a notebook record plus the family's current head). */
export function notebookProjectionFixture(
  notebook: Pick<Schema<"NotebookProjection">, "notebook_id"> & Partial<Schema<"NotebookProjection">>,
): Schema<"NotebookProjection"> {
  return { ...notebookViewFixture(notebook), current_family_head_run_id: null, ...notebook };
}

/** A compiled notebook planning context; override what a test is about. */
export function planningContextFixture(
  context: Partial<Schema<"PlanningContextView">> = {},
): Schema<"PlanningContextView"> {
  return {
    schema_version: "1.0",
    context_id: "ctx_fixture",
    context_profile: "notebook-plan/v1",
    notebook_id: "nb_fixture",
    run_family_id: "family_fixture",
    active_head_run_id: null,
    current_family_head_run_id: null,
    compiled_at: "2026-10-07T00:00:00Z",
    compile_duration_ms: null,
    generation_context_hash: "sha256:context",
    freshness_dependency_fingerprint: "fresh1:premises",
    graph_hash: null,
    projection_source: null,
    analysis_contract: {},
    user_focus: {},
    available_capabilities: [],
    active_run_summary: {},
    dataset_profile: {},
    artifact_summaries: [],
    artifact_type_counts: {},
    bounded_lineage: [],
    diagnostics: [],
    evidence_pack_refs: [],
    existing_option_summaries: [],
    omissions: [],
    budget_report: {},
    source_manifest: [],
    trace_id: null,
    ...context,
  };
}

/** A notebook's options listing. */
export function notebookOptionsFixture(
  options: Partial<Schema<"NotebookOptions">> = {},
): Schema<"NotebookOptions"> {
  return {
    context: planningContextFixture(),
    options: [],
    materializations: {},
    execution_results: {},
    trace_id: "trace_fixture",
    ...options,
  };
}
