# Workbench v1.6.2: NodeOperationContext + Read-only Ask AI

Subtitle: Context-First, Draft-Compatible lineage operations

## 1. Core Direction

Workbench v1.6.2 adopts a context-first approach for lineage graph operations.

The immediate goal is not to implement PipelineDraft, Compare, or AI-driven graph mutation. The goal is to standardize node operation semantics for existing executed lineage graphs.

`NodeOperationContext v1` is the central contract. It answers one question:

> When a user selects an executed lineage node in the current forest and active-head context, which owner run, op node, node hash, upstream path, evidence, artifacts, decisions, editable schema, and capabilities does this operation bind to?

All current node operation consumers must read from `NodeOperationContext`:

- `DetailHeader`
- `LineagePath`
- `NodeActionMenu`
- `Rerun`
- `AskAIContextPacket` generation

Future Compare must compose two resolved `NodeOperationContext` objects instead of deriving run ownership directly.

No node operation consumer may infer owner run, op node, lineage path, or active-head relationship directly from raw runs, selected node, or forest state.

`NodeOperationContext v1` supports executed lineage nodes only, including materialized, failed, and stale nodes that belong to persisted run lineage. Failed and stale nodes are supported only when they have persisted run lineage, `owner_run_id`, `op_node_id`, `node_hash`, and a resolvable lineage path.

`NodeOperationContext v1` does not support planned PipelineDraft nodes. If the resolver cannot produce a complete context, it must return an explicit failure result rather than a partial context object.

The frontend resolver is the entry point for UI operation semantics. The backend validator is the safety gate for write operations. Read-only consumers may use the frontend-resolved context, while write operations such as rerun must submit the resolved target and pass backend validation.

PipelineDraft is documented only as a compatibility model in this spec. The spec defines draft nodes, draft edges, node states, and materialization references, but does not implement draft graph editing, planned node resolution, execution scheduling, or AI-generated graph mutations in this phase.

## 2. NodeOperationContext v1 Shape

`NodeOperationContext v1` must be deterministic. If owner run or op node cannot be determined, the resolver must fail instead of guessing.

```ts
type NodeOperationContextV1 = {
  context_version: "node-operation-context/v1";
  context_kind: "executed_lineage_node";
  context_fingerprint: string;

  selection: SelectionContext;
  ownership: OwnershipContext;
  operation_target: OperationTargetContext;
  lineage_context: LineageContextSummary;
  node_payload: NodePayloadSummary;
  capabilities: NodeOperationCapabilities;
  comparison_readiness: ComparisonReadiness;
  context_diagnostics: ContextDiagnostics;
};
```

### 2.1 Selection

```ts
type SelectionContext = {
  forest_node_key: string;
  node_hash: string;
  display_label: string;
  kind: string;
  stage: string;
};
```

`forest_node_key` is the frontend forest identity, usually derived from `node_hash` and `op_node_id`. It is not the backend operation node id.

### 2.2 Ownership

```ts
type OwnershipContext = {
  active_head_run_id: string | null;

  candidate_run_refs: Array<{
    run_id: string;
    op_node_id: string;
    node_hash: string;
    is_active_head: boolean;
    path_contains_node: boolean;
  }>;

  candidate_run_ids: string[];
  shared_by_run_ids: string[];

  owner_run_id: string;
  owner_resolution:
    | "active_head_contains_node"
    | "selected_run_hint"
    | "single_candidate"
    | "manual_candidate_selection";

  rerun_of?: string | null;
  parent_run_id?: string | null;
};
```

`candidate_run_refs` carries the strong per-run mapping needed by current operations and future Compare. `candidate_run_ids` may remain for simple display, but consumers must not rederive operation targets from raw runs.

`manual_candidate_selection` must be produced only after an explicit user choice. It must not be used as an automatic fallback.

### 2.3 Operation Target

```ts
type OperationTargetContext = {
  owner_run_id: string;
  op_node_id: string;
  node_hash: string;
  node_state: "materialized" | "failed" | "stale";
  editable_schema_source?: "run_inputs" | "capabilities";
};
```

`op_node_id` is the backend operation node id, used as the rerun `from_node`. It must not be confused with `forest_node_key`.

### 2.4 Lineage Context

```ts
type LineageContextSummary = {
  path_run_id: string;
  upstream_path: LineageNodeSummary[];
  downstream_hint?: {
    has_downstream: boolean;
    downstream_count?: number;
  };
  active_head_path_contains_node: boolean;
};
```

`upstream_path` is from the `owner_run_id` perspective, not the merged forest's global path. `path_run_id` must equal `ownership.owner_run_id`.

### 2.5 Node Payload

```ts
type NodePayloadSummary = {
  decisions: DecisionSummary[];
  artifacts: ArtifactSummary[];
  editable_schema: EditableControl[] | null;
  params: Record<string, unknown>;
  metrics?: Record<string, unknown>;
  execution_diagnostics?: DiagnosticSummary[];
};
```

`execution_diagnostics` are diagnostics from node execution or model output. They are separate from resolver diagnostics.

### 2.6 Capabilities

```ts
type NodeOperationCapabilities = {
  can_rerun: boolean;
  can_ask_ai: boolean;
  can_compare: boolean;
  can_rollback_focus: boolean;
  can_edit_params: boolean;
  disabled_reasons: string[];
};
```

Capability flags are computed by the resolver and consumed by action surfaces. Consumers must not independently infer these flags from raw runs.

### 2.7 Comparison Readiness

```ts
type ComparisonReadiness = {
  can_compare: boolean;
  candidate_run_ids: string[];
  active_head_run_id: string | null;
  owner_run_id: string;
  parent_run_id?: string | null;
  shared_by_run_ids: string[];
};
```

Compare is a future consumer. v1.6.2 only exposes readiness metadata.

### 2.8 Context Diagnostics

```ts
type ContextDiagnostics = {
  warnings: string[];
  resolution_notes: string[];
};
```

`context_diagnostics` are generated by the resolver. They describe owner resolution, ambiguity, stale state, or visibility limitations. They are not node execution diagnostics.

### 2.9 Artifact Summary

```ts
type ArtifactSummary = {
  artifact_id: string;
  name: string;
  artifact_type: ArtifactType;
  mime_type?: string;
  size_bytes?: number;
  producer_node_id?: string;

  ai_visibility:
    | "metadata_only"
    | "summary_preview"
    | "redacted_preview"
    | "not_included";

  summary?: string;

  preview?: {
    kind: "text" | "json" | "table";
    truncated: boolean;
    content?: unknown;
  };

  redactions?: Array<
    | "raw_values_removed"
    | "large_table_truncated"
    | "binary_content_excluded"
    | "full_text_excluded"
    | "sensitive_columns_removed"
  >;
};
```

Artifact summaries must encode AI visibility instead of leaving later consumers to guess what the AI can see.

### 2.10 Resolve Result

```ts
type ResolveNodeOperationContextResult =
  | { ok: true; context: NodeOperationContextV1 }
  | {
      ok: false;
      reason:
        | "unsupported_planned_node"
        | "missing_owner_run"
        | "ambiguous_owner_run"
        | "missing_op_node"
        | "missing_node_hash"
        | "context_stale";

      selected_node_key: string;
      active_head_run_id?: string | null;
      candidate_run_ids?: string[];
      node_hash?: string;
      detail?: string;
    };
```

`context_fingerprint` must at minimum cover:

- `forest_node_key`
- `node_hash`
- `owner_run_id`
- `op_node_id`
- `active_head_run_id`
- run lineage version or `updated_at`

`AskAIContextPacket` may only be generated from a successful `NodeOperationContextV1`. If context resolution fails, Ask AI must show the resolver failure state instead of generating an AI packet.

## 3. Resolver Rules / Owner Resolution

The resolver determines which run and op node a selected forest node operation binds to.

Owner resolution order:

```text
active_head_contains_node
-> selected_run_hint
-> single_candidate
-> manual_candidate_selection
-> failure
```

### 3.1 Active Head Contains Node

If `active_head_run_id` exists and the selected node's `candidate_run_refs` contains that run:

```text
owner_run_id = active_head_run_id
owner_resolution = "active_head_contains_node"
```

For graph-level node operations, active head is the default owner when it contains the selected node.

### 3.2 Selected Run Hint

If active head does not contain the node and the UI provides an explicit `selected_run_hint`, the hint may be used only when it resolves to a candidate run ref with a matching `node_hash` and `op_node_id`.

```text
owner_run_id = selected_run_hint
owner_resolution = "selected_run_hint"
```

`selected_run_hint` must come from explicit UI state, such as a run-scoped drawer, branch view, or history panel. It must not be derived from candidate array order.

If `active_head_run_id` contains the selected node, `selected_run_hint` must not silently override it unless the operation comes from an explicitly run-scoped surface or the user has completed manual candidate selection.

### 3.3 Single Candidate

If there is no active-head match and no valid selected run hint, but the node belongs to exactly one candidate run:

```text
owner_run_id = only candidate run
owner_resolution = "single_candidate"
```

This is deterministic because no ownership ambiguity exists.

### 3.4 Manual Candidate Selection

If the node belongs to multiple candidate runs and neither active head nor selected hint resolves ownership, the resolver must initially fail:

```ts
{ ok: false, reason: "ambiguous_owner_run" }
```

The UI may then show candidate runs and ask the user to choose the operation owner. Only after explicit user selection may the resolver return:

```text
owner_resolution = "manual_candidate_selection"
```

Manual selection must not trigger rerun, compare, branch switch, or active-head switch by itself. It only re-runs resolution with a user-confirmed owner.

### 3.5 Failure Rule

If owner run or op node cannot be determined, the resolver must return failure instead of a partial context.

No successful `NodeOperationContextV1` may be produced from guessed run ownership.

Ambiguity is a valid resolver result, not an error to be hidden.

## 4. Consumer Integration / Data Flow

### 4.1 Shared Data Flow

```text
forest state + selected forest node + active head + optional run-scoped hint
-> resolve NodeOperationContextV1
-> read-only consumers render from context
-> write consumers submit operation target to backend validator
```

If resolution succeeds:

```text
DetailHeader / LineagePath / NodeActionMenu / AskAIContextPacket / Rerun payload
```

If resolution fails:

```text
ResolverFailureState
disable rerun / edit / Ask AI packet / compare
```

Consumers must not reconstruct `owner_run_id`, `op_node_id`, `upstream_path`, or active-head relationship from raw runs.

### 4.2 DetailHeader

`DetailHeader` is a read-only consumer. It reads:

- `context.selection`
- `context.ownership`
- `context.operation_target`
- `context.context_diagnostics`

It may display:

- `display_label`
- `kind` and `stage`
- `owner_run_id`
- `owner_resolution`
- `node_state`
- `active_head_path_contains_node`
- warnings

On resolver failure, it shows `ResolverFailureState`, does not display a fabricated owner run, and does not expose direct actions.

### 4.3 LineagePath

`LineagePath` reads:

- `context.lineage_context.path_run_id`
- `context.lineage_context.upstream_path`
- `context.lineage_context.active_head_path_contains_node`

`upstream_path` is the owner-run path, not a merged forest path.

On resolver failure, `LineagePath` may display the selected node's graph location, but must not display owner-run-specific path information.

### 4.4 NodeActionMenu

`NodeActionMenu` reads:

- `context.capabilities`
- `context.comparison_readiness`
- `context.context_diagnostics`

It must not independently infer:

- `can_rerun`
- `can_ask_ai`
- `can_compare`
- `can_edit_params`

On resolver failure, it disables rerun, edit, Ask AI, and compare. For `ambiguous_owner_run`, it may show a disambiguation entry. This entry only lets the user choose a candidate run, then re-runs the resolver to produce `manual_candidate_selection`.

### 4.5 Rerun

Rerun is the primary v1 write consumer. It reads the operation target from context and submits it to the backend validator.

```ts
type NodeWriteOperationRequestV1 = {
  request_id: string;
  operation: "rerun";

  context_version: "node-operation-context/v1";
  context_fingerprint: string;

  owner_run_id: string;
  op_node_id: string;
  node_hash: string;
  forest_node_key: string;

  owner_resolution: OwnerResolution;
  active_head_run_id: string | null;
};
```

Rerun must not submit ambiguous fields such as only `node_hash`, only `forest_node_key`, or a run inferred from `runs[0]`.

### 4.6 Ask AI

Ask AI is a read-only consumer. It can only generate `AskAIContextPacketV1` from a successful `NodeOperationContextV1`.

It cannot read:

- raw runs
- raw forest state
- full artifacts
- full datasets

On resolver failure, Ask AI shows the failure state and does not generate a packet.

### 4.7 Future Compare

Compare is not implemented in v1.6.2. Future Compare must compose two successful `NodeOperationContextV1` objects.

```ts
type CompareOperationContextV1 = {
  left: NodeOperationContextV1;
  right: NodeOperationContextV1;
  comparison_scope: {
    params: boolean;
    decisions: boolean;
    artifacts: boolean;
    metrics: boolean;
    diagnostics: boolean;
    upstream_path: boolean;
  };
};
```

This phase requires `comparison_readiness` fields only. It does not require Compare UI, Compare API, or diff rendering.

### 4.8 Backend Validator

The backend is not the primary UI resolver. It is the safety gate for writes.

It validates the submitted operation target, rejects stale or mismatched contexts, and never blindly trusts frontend context fields.

### 4.9 Consumer Invariants

1. Read-only consumers may render from frontend-resolved `NodeOperationContextV1`.
2. Write consumers must submit operation target fields and pass backend validation.
3. No consumer may reconstruct owner run, op node, lineage path, or active-head relationship from raw runs.
4. Resolver failure is a first-class UI state; consumers must not silently degrade into guessed context.

## 5. Ask AI Context Packet v1

Ask AI v1 is a read-only explanatory layer over `NodeOperationContextV1`. It is not an action proposal layer.

```ts
type AskAIContextPacketV1 = {
  packet_version: "ask-ai-context/v1";
  source_context_version: "node-operation-context/v1";
  context_fingerprint: string;

  packet_scope: {
    scope_type: "selected_node";
    includes_upstream_path: true;
    includes_downstream_nodes: false;
    includes_full_run: false;
  };

  selection: SelectionContext;
  ownership: AskAIOwnershipSummary;
  operation_target: AskAIOperationTargetSummary;
  lineage_summary: AskAILineageSummary;
  node_summary: AskAINodeSummary;
  artifacts: ArtifactSummary[];
  context_diagnostics: ContextDiagnostics;

  context_visibility_notice: {
    artifact_policy: "metadata_and_safe_preview_only";
    full_datasets_included: false;
    full_reports_included: false;
    binary_artifacts_included: false;
  };

  allowed_response_modes: Array<
    | "explain"
    | "summarize"
    | "identify_risks"
    | "suggest_questions"
  >;

  response_guardrails: {
    advisory_text_only: true;
    executable_actions_allowed: false;
    graph_mutations_allowed: false;
    backend_payloads_allowed: false;
    file_reads_allowed: false;
    must_disclose_visibility_limits: true;
  };
};
```

### 5.1 Artifact Visibility Policy

Artifacts in Ask AI v1 are not raw files.

Policy:

- metadata is always allowed
- allowlisted small previews are allowed
- full datasets are forbidden
- full reports are forbidden
- binary artifacts are forbidden
- AI-initiated file reads are forbidden

Preview caps:

- `max_preview_chars_per_artifact: 2000`
- `max_total_preview_chars: 8000`
- small table preview: at most 10 rows and 20 columns

### 5.2 Allowed Behavior

Ask AI v1 may explain:

- what the node does
- which owner run it belongs to
- how it relates to the active head
- upstream nodes, decisions, and params
- artifacts and execution diagnostics
- risks or manual check points
- editable fields from `editable_schema_summary`
- useful follow-up questions

AI may explain editable fields from `editable_schema_summary`, but must not generate or submit executable patches in v1.

### 5.3 Forbidden Outputs

Ask AI v1 must not return:

- rerun action
- patch action
- graph mutation
- rollback operation
- compare execution
- PipelineDraft node creation
- artifact file-read request
- backend operation payload

Ask AI v1 returns advisory text only. It cannot create or modify graph state, bypass `NodeOperationContext`, or infer hidden context from raw runs, raw forest state, or artifact files.

### 5.4 Debug and Audit Preview

Ask AI v1 should expose a developer/debug context preview showing the exact `AskAIContextPacket` sent to the AI service, including artifact visibility levels and redactions. This preview is for verification and audit only, not a user-editable payload.

## 6. Backend Validation / Write Safety

The backend is not the primary v1 UI context resolver, but it is the authoritative safety gate for write operations.

v1 only supports:

```text
operation = "rerun"
```

Future write operations must extend the operation union explicitly and define their own validator rules.

### 6.1 Request Logging

The backend must log:

- `request_id`
- `operation`
- `context_version`
- `context_fingerprint`
- `owner_run_id`
- `op_node_id`
- `node_hash`
- `active_head_run_id`
- validation result
- failure reason

v1 does not require full idempotency, but `request_id` must support audit and duplicate-submit debugging.

### 6.2 Validator Rules

The backend validator must check:

1. `context_version` is supported.
2. `owner_run_id` exists.
3. `op_node_id` exists in `owner_run_id`.
4. `op_node_id` has matching `node_hash`.
5. `forest_node_key` is consistent when the backend has enough mapping information.
6. Node state is eligible for the requested operation.
7. Request does not target a planned or draft node.
8. `context_fingerprint` is still valid for current run lineage version or `updated_at`.
9. `active_head_run_id` remains consistent with the persisted context that produced ownership resolution.

`forest_node_key` is a UI selection identity and audit field. The authoritative write target is `owner_run_id + op_node_id + node_hash`.

`active_head_run_id` validates the UI context under which ownership was resolved. It must not override `owner_run_id` as the rerun source.

### 6.3 Structured Errors

```ts
type NodeWriteValidationError =
  | {
      code: "unsupported_context_version";
      status: 400;
      message: string;
    }
  | {
      code: "invalid_operation_target";
      status: 400;
      message: string;
    }
  | {
      code: "operation_not_allowed";
      status: 403;
      message: string;
    }
  | {
      code: "context_stale";
      status: 409;
      message: string;
      latest_context_hint?: unknown;
    }
  | {
      code: "context_mismatch";
      status: 409;
      message: string;
      mismatch_fields: string[];
    };
```

On `context_stale` or `context_mismatch`, the frontend must:

1. stop the write operation
2. refresh forest and runs
3. re-run `resolveNodeOperationContext`
4. show a stale-context message
5. require the user to retry from the refreshed context

The frontend must not automatically retry with the old payload.

### 6.4 Rerun Success Response

```ts
type RerunResponseV1 = {
  new_run_id: string;
  new_active_head_id: string;

  focus: {
    forest_node_key: string;
    op_node_id: string;
    node_hash: string;
  } | null;

  rerun_from: {
    owner_run_id: string;
    op_node_id: string;
    node_hash: string;
    forest_node_key: string;
  };

  accepted_context?: {
    context_version: "node-operation-context/v1";
    context_fingerprint: string;
    owner_run_id: string;
    op_node_id: string;
    node_hash: string;
    validated_at: string;
  };
};
```

`focus` should normally be returned. `focus: null` is allowed only as degraded success when the backend created the new run but cannot map the new focus node back to a `forest_node_key`.

### 6.5 Backend Invariants

1. Backend validator is authoritative for write safety.
2. Frontend context fields are submitted for validation, not blindly trusted.
3. Context mismatch or stale state must fail closed.
4. Rerun must fork from `owner_run_id`, never from `runs[0]` or an implicit default.
5. A successful rerun should return a focus target for the new run whenever possible.
6. `active_head_run_id` is validation context, not the rerun source. The rerun source is always `owner_run_id + op_node_id`.

## 7. Rerun UX / Active Head / Focus Semantics

Rerun is a user-initiated branch creation operation. A successful rerun changes the operational focus to the new child run.

In v1, rerun creates one child run, and that child run becomes the new active head. `new_active_head_id` should normally equal `new_run_id`. If they differ in a future version, the response must explain why.

### 7.1 Default Success Path

When `RerunResponseV1.focus` exists, the frontend must:

1. `setActiveHead(response.new_active_head_id)`
2. refresh forest and run heads
3. focus branch for `response.new_active_head_id`
4. select `response.focus.forest_node_key`
5. re-resolve `NodeOperationContextV1` for the selected new node
6. refresh `DetailDrawer` from the new context
7. show toast: "Rerun completed. Switched to new head."

After success, current operational context must move to the new run rather than staying bound to the old source node.

### 7.2 Source Node Navigation

UI may provide:

- View source node
- View previous head

This is navigation only. It does not change the default post-rerun operational focus.

Source navigation should be based on `response.rerun_from`, not stale pre-rerun UI selection state. The target context must be re-resolved after navigation.

### 7.3 Focus Null Degraded Success

If `focus: null`, the frontend must:

1. `setActiveHead(response.new_active_head_id)`
2. refresh forest and run heads
3. attempt to re-resolve likely focus from the new run using `accepted_context` or `rerun_from`
4. if unresolved, keep active head on the new run
5. show toast: "Rerun completed, but focus target could not be resolved automatically."

The frontend must not use `runs[0]` or candidate array order to guess focus.

### 7.4 Async Rerun

```ts
type RerunLifecycleState =
  | "submitted"
  | "pending_child_run"
  | "running"
  | "materialized"
  | "failed"
  | "request_failed";
```

If a child run or pending run id exists, the active head may switch to that child run. If the backend cannot return `new_run_id` yet, the UI must keep the source context and show running state until the child run is known.

`request_failed` means the request failed before child run creation. It must not change active head.

`failed` means the child run exists but node execution failed. The new run still becomes active head if the failed node is persisted in run lineage.

### 7.5 Rerun UX Invariants

1. A successful rerun changes operational focus to the new child run.
2. The source node remains navigable, but it is not the active operational context after success.
3. `focus: null` is a degraded success, not a normal backend shortcut.
4. Failed child nodes are valid executed lineage nodes if persisted in run lineage.
5. UI must never guess focus or owner from `runs[0]` or candidate array order.
6. `request_failed` before child run creation must not change active head.
7. Failed execution after child run creation still switches to the new child run if the failed node is persisted.

## 8. PipelineDraft Compatibility Model

PipelineDraft is not implemented in v1.6.2. This section only defines the future-compatible object model to avoid blocking graph-first Workbench evolution.

### 8.1 Why PipelineDraft Exists

`RunLineage` describes executed runs: nodes, parameters, decisions, artifacts, and paths created by execution.

Future Workbench needs a graph that exists before execution:

```text
select dataset
-> add cleaning / imputation / transform / model / report nodes
-> execute whole graph or selected nodes
```

That graph is a `PipelineDraft`.

### 8.2 PipelineDraft vs RunLineage

```text
PipelineDraft = planned graph / editable analysis plan
RunLineage = executed graph / persisted execution result
```

Identity distinctions:

- `draft_node_id` belongs to a planned graph.
- `op_node_id` belongs to an executed run.
- `node_hash` identifies executed lineage identity in v1.
- `artifact_id` identifies produced execution artifacts.

Future draft graphs may introduce `draft_config_hash` or `plan_hash`, but `NodeOperationContext v1` must not use `node_hash` to identify planned nodes.

### 8.3 Core Objects

```ts
type PipelineDraft = {
  draft_id: string;
  name?: string;
  created_at: string;
  updated_at: string;

  nodes: DraftNode[];
  edges: DraftEdge[];

  latest_materialization?: {
    run_id: string;
    materialized_at: string;
  };
};
```

`latest_materialization` is a convenience pointer, not the full materialization history. The authoritative mapping lives on `materialized_refs`.

```ts
type DraftNode = {
  draft_node_id: string;

  node_type:
    | "dataset"
    | "cleaning"
    | "imputation"
    | "filter"
    | "transform"
    | "model"
    | "diagnostics"
    | "report";

  config: Record<string, unknown>;

  state:
    | "planned"
    | "running"
    | "materialized"
    | "failed"
    | "stale";

  materialized_refs?: MaterializedNodeRef[];
};
```

`DraftNode.state` is a planning-surface state. It summarizes whether a draft node has pending, running, materialized, failed, or stale execution references. It does not replace the execution state of the referenced op node.

```ts
type DraftEdge = {
  draft_edge_id: string;
  from_draft_node_id: string;
  to_draft_node_id: string;
  edge_type?: "data_flow" | "dependency" | "report_input";
};
```

```ts
type MaterializedNodeRef = {
  run_id: string;
  op_node_id: string;
  node_hash: string;
  artifact_ids: string[];
  materialized_at: string;
};
```

### 8.4 Materialization Relationship

A draft node may be materialized multiple times.

```text
DraftNode
-> materialize
-> RunLineage op node
-> artifacts
```

Materialization creates references from draft nodes to executed run lineage nodes. It does not mutate a draft node into an op node.

### 8.5 Relationship to NodeOperationContext v1

`NodeOperationContextV1` does not resolve planned nodes.

If a planned draft node is selected in a future graph surface, the v1 resolver must return:

```ts
{
  ok: false,
  reason: "unsupported_planned_node",
  selected_node_key: string
}
```

`NodeOperationContextV1` is effectively the materialized/executed branch of a future graph node context union.

Future support may use:

```ts
type GraphNodeContext =
  | ExecutedLineageNodeContext
  | DraftNodeOperationContext;
```

### 8.6 PipelineDraft Invariants

1. v1.6.2 does not support planned node operations.
2. `NodeOperationContext v1` fields must not assume every future graph node has a `run_id`, `op_node_id`, `node_hash`, or artifacts.
3. `draft_node_id`, `op_node_id`, `node_hash`, and `artifact_id` are distinct identities and must not be reused interchangeably.
4. Materialization creates references from draft nodes to executed run lineage nodes; it does not mutate a draft node into an op node.
5. Future draft support must be introduced as a separate context branch, not as a partial or degraded `NodeOperationContextV1`.
6. `node_hash` in v1 refers to executed lineage identity. Planned draft nodes may need a future `draft_config_hash` or `plan_hash`, but must not be treated as executed `node_hash`.

## 9. Implementation Plan / PR Breakdown

### Milestone A: Context Foundation

#### PR 1: NodeOperationContext Resolver

Includes:

- `NodeOperationContextV1` types
- `ResolveNodeOperationContextResult`
- `candidate_run_refs`
- owner resolution rules
- `context_fingerprint` generation
- resolver failure states
- `explainResolveNodeOperationContext(...)` developer/debug helper
- unit tests for active head, selected run hint, single candidate, manual selection, and ambiguous failure

`explainResolveNodeOperationContext(...)` should output:

- selected forest node
- `candidate_run_refs`
- `active_head_run_id`
- `selected_run_hint`
- chosen `owner_resolution`
- failure reason
- `context_fingerprint` inputs

#### PR 2: Read-only Consumer Migration

Includes:

- `DetailHeader` reads context
- `LineagePath` reads `context.lineage_context`
- `NodeActionMenu` reads capabilities
- `ResolverFailureState` UI
- ambiguous owner disambiguation entry

The ambiguous disambiguation entry is limited to:

```text
choose candidate run
-> re-run resolver
-> produce manual_candidate_selection
```

It does not trigger rerun, compare, branch switch, or active-head switch.

### Milestone B: Safe Rerun

#### PR 3: Rerun Write Path + Backend Validator

Includes:

- `NodeWriteOperationRequestV1`
- `request_id`
- backend validator
- `context_fingerprint` validation
- structured validation errors
- rerun source = `owner_run_id + op_node_id`
- `active_head_run_id` as validation context only

#### PR 4: Rerun Active Head + Focus UX

Includes:

- `RerunResponseV1.focus`
- `setActiveHead(new_active_head_id)`
- focus new branch
- select new focus node
- refresh `DetailDrawer` from new context
- source node navigation via `rerun_from`
- `focus: null` degraded path
- async and failed rerun states

### Milestone C: Read-only AI + Regression Gates

#### PR 5: AskAIContextPacket + Debug Preview

Includes:

- `AskAIContextPacketV1` generator
- `packet_scope`
- artifact visibility policy
- redactions
- response guardrails
- `context_visibility_notice`
- developer/debug context preview

PR 5 is a contract/audit PR and can ship behind a developer flag before user-facing Ask AI is enabled.

#### PR 6: Read-only Ask AI Q&A

Includes:

- Ask AI panel
- read-only explanatory prompts
- `allowed_response_modes`
- visibility limit disclosure
- guard against executable outputs

#### PR 7: Regression Gates + Invariants

Includes:

- shared node plus active head not `runs[0]` rerun regression
- ambiguous owner failure tests
- backend context mismatch tests
- Ask AI blocked artifact tests
- rerun focus tests
- golden 0-drift gate
- browser acceptance seed project

Each PR must include local tests for the behavior it introduces. PR 7 consolidates cross-feature regression gates and browser acceptance coverage.

Recommended order:

```text
PR 1 -> PR 2 -> PR 3 -> PR 4 -> PR 5 -> PR 6 -> PR 7
```

If needed, PR 3 and PR 4 may be combined, and PR 5 and PR 6 may be combined. Resolver, rerun backend, and Ask AI should not all be combined into one PR.

## 10. Non-goals / Scope Boundaries

### 10.1 Explicit Non-goals for v1.6.2

v1.6.2 does not implement:

- PipelineDraft operations
- planned node resolver
- draft graph editor
- drag/drop node creation
- Compare UI
- Compare API
- diff renderer
- AI action proposal
- AI patch generation
- AI-triggered rerun
- AI-created PipelineDraft nodes
- rollback write operation
- full artifact reading
- full dataset inclusion in Ask AI
- full report inclusion in Ask AI
- stale propagation algorithm
- execution scheduler
- full data processing node library

### 10.2 Allowed Future Compatibility Only

PipelineDraft and Compare are documented only as future-compatible models and consumers. Their presence in this spec does not imply implementation in v1.6.2.

### 10.3 Scope Guardrail

Any implementation that requires planned node operations, AI-generated executable actions, Compare execution, or full artifact ingestion must be moved to a future spec.

## 11. Test Matrix / Acceptance Gates

### 11.1 Blocker Regression Matrix

| Risk | Scenario | Expected result | Gate |
| --- | --- | --- | --- |
| Wrong owner run | Selected node is shared by multiple runs; active head is not `runs[0]` | Resolver picks active head if it contains node | Unit + browser |
| `runs[0]` regression | Rerun from active head that is not first in array | Backend forks from `owner_run_id + op_node_id`, never `runs[0]` | Backend + integration |
| Ambiguous owner | Shared node, active head does not contain it, no selected hint | Resolver returns `ambiguous_owner_run` | Unit |
| Invalid fallback | Multiple candidates with no owner | No successful context is produced | Unit |
| Stale context | Run lineage updated after context generated | Backend returns `context_stale` or `context_mismatch` | Backend |
| Wrong focus | Rerun succeeds | UI switches active head and selects new focus node | Browser |

### 11.2 Non-blocker Behavior Matrix

| Area | Scenario | Expected result |
| --- | --- | --- |
| Resolver failure | Missing op node | `ResolverFailureState` shown; actions disabled |
| Manual selection | User chooses candidate run | Resolver re-runs with `manual_candidate_selection` |
| DetailHeader | Successful context | Displays owner, node state, warnings |
| LineagePath | Successful context | Shows owner-run upstream path |
| NodeActionMenu | Failed context | Disables rerun, edit, Ask AI, compare |
| `focus: null` | Rerun succeeds but no focus target | Active head switches; UI refreshes; degraded toast shown |
| Failed child run | Child run persisted but execution failed | New run becomes active; failed node selected |

### 11.3 Ask AI Safety / Visibility Matrix

| Scenario | Expected result |
| --- | --- |
| Resolver fails | No `AskAIContextPacket` generated |
| Artifact is dataset | Metadata only or not included |
| Artifact is full report | Metadata only or summary preview; no full text |
| Artifact is diagnostics summary | Safe preview allowed within caps |
| Preview too large | Truncated and marked `truncated: true` |
| Redacted preview | `redactions` populated |
| User asks AI to rerun | AI refuses or explains v1 is advisory only |
| AI response contains backend payload | Blocked or not rendered as action |
| AI claims full artifact knowledge | Must disclose visibility limits |

### 11.4 Release Gates

Release gates:

1. All resolver unit tests pass.
2. Backend validator tests pass.
3. Rerun no longer depends on `runs[0]`.
4. Ambiguous owner produces resolver failure, not fallback.
5. `AskAIContextPacket` is generated only from `ok: true` context.
6. Full datasets, full reports, and binary artifacts are not included in Ask AI packet.
7. Rerun success switches active head to the new child run.
8. Rerun focus selects the new node when focus is returned.
9. `context_stale` and `context_mismatch` fail closed and require re-resolve.
10. Browser acceptance seed project passes.
11. Existing lineage forest rendering has no golden drift unless intentionally updated.
