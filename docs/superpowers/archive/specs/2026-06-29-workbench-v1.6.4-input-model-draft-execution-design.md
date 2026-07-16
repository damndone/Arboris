# Workbench v1.6.4: Graph-first MVP - Input to Model Draft Execution

## 1. Direction

v1.6.4 introduces the first executable `PipelineDraft` slice without building a full pipeline builder.

The release goal is:

```text
Convert one eligible executed model node into a saveable, validateable, executable
minimal PipelineDraft, render it as an unexecuted InputNode -> ModelNode graph,
and execute it as a child run of the source run / source model node.
```

This is the first Workbench version where an unexecuted graph exists as a first-class backend object.
It is not a rerun wrapper, a transform editor, a dataset upload flow, or the final unified Graph Workbench.

## 2. Product Loop

The only shipped product loop is:

```text
Lineage Detail eligible executed model node
-> Open as Draft Graph
-> create PipelineDraft
-> navigate to /pipeline-drafts/{draft_id}
-> show fixed InputNode -> ModelNode
-> edit ModelNode editable_schema params
-> Save changes
-> Validate Draft
-> receive validated_draft_hash
-> Execute Draft with validated_draft_hash
-> server revalidates and freezes executed_pipeline_draft snapshot
-> create child run of source run / source model node
-> focus child, or pending_index poll
-> Compare with source
```

The canonical entry point is node-level:

```text
Lineage Detail -> eligible executed model node -> Open as Draft Graph
```

A run-level `Open in Graph` shortcut may exist only when the run has exactly one eligible executable model node. If more than one eligible model node exists, the UI must require explicit model-node selection or route the user to Lineage Detail. The shortcut must not guess source model node, owner run, operation node, or input binding.

Eligible means:

```text
NodeOperationContext resolves successfully
editable_schema is available
source node hash and source context fingerprint are verifiable
source input binding can be resolved
```

## 3. Scope

v1.6.4 does:

```text
PipelineDraft first-class JSON store
InputNode -> ModelNode graph shape
dedicated Draft Graph View
InputNode read-only binding to source run_inputs / input fingerprint
ModelNode editable_schema-driven params
strong preflight Validate Draft
validated_draft_hash execution gate
POST /pipeline-drafts/{draft_id}/execute
rerun_child execution enabled
new_run reserved but disabled
NEW_RUN_EXECUTION_NOT_ENABLED
executed_pipeline_draft snapshot
```

v1.6.4 does not do:

```text
new uploaded dataset UI
new_run execution
transform / clean / feature-engineering nodes
free DAG editing
node palette
drag-drop builder
multi-model graph
template library
AI graph generation
unified Graph Workbench
```

The separate Draft Graph View is an implementation staging choice, not the final product architecture.
The long-term target remains a unified Graph Workbench where executed, draft, pending, and failed nodes can be shown in one graph. The data semantics must stay separate:

```text
run = immutable evidence
draft = mutable plan
executed draft snapshot = immutable provenance
```

## 4. Data Model and Storage Boundary

Core boundary:

```text
PipelineDraft = first-class mutable planning object
Run = immutable execution evidence
ExecutedPipelineDraft = immutable execution snapshot
```

A draft may reference runs and nodes, but no run owns the mutable draft.

Mutable drafts are stored under:

```text
data/pipeline_drafts/{draft_id}.json
```

When a draft is executed, the produced run stores an immutable snapshot:

```text
runs/{new_run_id}/executed_pipeline_draft.json
```

The produced run metadata records:

```ts
{
  execution_origin: "pipeline_draft",
  draft_id: string,
  executed_draft_hash: string,
  execution_mode: "rerun_child",

  rerun_from_run_id: string,
  rerun_from_model_node_id: string,
  rerun_from_op_node_id: string,

  template_source_run_id: string,
  template_source_model_node_id: string,
  template_source_op_node_id: string
}
```

In v1.6.4, `rerun_from_*` and `template_source_*` normally match. They remain separate because future `new_run` template execution may have a template source without entering the source run's rerun family.

`draft_id` is server-generated, URL-safe, and path-safe. It must not contain path separators. All draft reads and writes go through the PipelineDraftStore abstraction; no API may resolve arbitrary user-provided file paths.

### 4.1 PipelineDraft v1

```ts
type PipelineDraftV1 = {
  draft_id: string;
  schema_version: "pipeline_draft.v1";
  created_at: string;
  updated_at: string;
  status: "draft";

  created_from?: {
    source_type: "run";
    source_run_id: string;
    source_model_node_id: string;
    source_op_node_id: string;
    source_node_hash: string;
    source_context_fingerprint: string;
    source_input_fingerprint: string;
  };

  graph: {
    nodes: [InputDatasetNode, ModelDraftNode];
    edges: [{ from: string; to: string }];
  };

  default_execution_mode: "rerun_child" | "new_run";
};
```

`created_from` is optional only for future `new_run`, template, or blank-draft paths. In v1.6.4 UI-created drafts, `created_from` is required because only `rerun_child` execution is enabled.

### 4.2 InputDatasetNode

```ts
type InputDatasetNode = {
  node_id: string;
  node_type: "input.dataset";

  source_type: "run_input" | "upload";
  run_input_id?: string;
  upload_sha?: string;
  dataset_snapshot_id?: string;

  schema_fingerprint: string;
  input_fingerprint: string;
  row_count?: number;
  column_count?: number;
  columns_summary?: Array<{ name: string; dtype?: string }>;

  status: "bound" | "missing" | "invalid";
};
```

v1.6.4 UI creates only `source_type: "run_input"`. `upload` is contract-reserved for future versions.

### 4.3 ModelDraftNode

```ts
type ModelDraftNode = {
  node_id: string;
  node_type: "model";

  model_family: string;
  model_type: string;

  schema_id: string;
  editable_schema: unknown;
  editable_schema_hash: string;

  source_ref: {
    source_run_id: string;
    source_model_node_id: string;
    source_op_node_id: string;
    source_node_hash: string;
    source_context_fingerprint: string;
  };

  source_params: Record<string, unknown>;
  params: Record<string, unknown>;
};
```

For v1.6.4 single-model drafts, `ModelDraftNode.source_ref` must match `PipelineDraft.created_from`. Any mismatch is validation-blocking.

`editable_schema` is snapshotted into the draft. `editable_schema_hash` identifies the snapshotted schema content used to validate `params`. `schema_id` must still resolve to a supported execution adapter at execution time.

`source_params` and `params` are editable value maps, not JSON Patch documents:

```text
source_params = source editable parameter value map
params = current editable parameter value map
actual rerun patch = diff(source_params, params) after editable_schema validation
```

The draft must not represent:

```text
nested JSON patch
dataset patch
code patch
artifact patch
non-editable model field mutation
```

### 4.4 Hashes

```text
draft_hash = canonical hash of executable draft content
validated_draft_hash = successful validation hash
executed_draft_hash = hash of frozen executable draft payload
```

The executable draft hash includes:

```text
schema_version
created_from
graph.nodes
graph.edges
default_execution_mode
```

It excludes volatile or UI-only metadata:

```text
created_at
updated_at
status
UI layout state
last_validation_result
temporary editor state
```

The executed snapshot wrapper has this shape:

```ts
{
  executed_at: string;
  source_draft_id: string;
  executed_draft_hash: string;
  execution_request: {
    execution_mode: "rerun_child";
    validated_draft_hash: string;
  };
  draft: PipelineDraftV1;
}
```

The hash is computed from the frozen executable draft payload, not the wrapper.

## 5. API Contract

### 5.1 Create from node

```http
POST /pipeline-drafts/from-node
```

Request:

```ts
{
  source_run_id: string;
  source_model_node_id: string;
  source_op_node_id: string;
  source_node_hash: string;
  source_context_fingerprint: string;
}
```

Behavior:

```text
resolve NodeOperationContext server-side
verify eligible executed model node
verify editable_schema is available
verify resolved source_node_hash matches request.source_node_hash
verify resolved context_fingerprint matches request.source_context_fingerprint
extract source run_inputs / input_fingerprint
extract editable_schema and source_params
create PipelineDraftV1 with default_execution_mode = "rerun_child"
create data/pipeline_drafts/{draft_id}.json
return PipelineDraftV1 + draft_hash
```

Failure is fail-closed. The server must not guess source node, owner run, operation node, or input binding.

### 5.2 Read draft

```http
GET /pipeline-drafts/{draft_id}
```

Response:

```ts
{
  draft: PipelineDraftV1;
  draft_hash: string;
}
```

Behavior:

```text
load data/pipeline_drafts/{draft_id}.json
compute current draft_hash from executable draft content
return draft + draft_hash
```

### 5.3 Update draft params

```http
PATCH /pipeline-drafts/{draft_id}
```

Request:

```ts
{
  model_node_id: string;
  base_draft_hash: string;
  params: Record<string, unknown>;
}
```

Behavior:

```text
load draft
verify request.base_draft_hash matches current draft_hash
verify model_node_id exists and is a ModelDraftNode
verify params contain only editable_schema-allowed fields
verify field types / enums / ranges
reject nested JSON patch
reject dataset patch
reject code patch
reject artifact patch
reject non-editable model field mutation
replace ModelDraftNode.params with request.params
update updated_at
return PipelineDraftV1 + draft_hash
```

This is a controlled params update endpoint, not a generic JSON Patch endpoint.

If `base_draft_hash` does not match the current executable draft hash, the server returns `DRAFT_HASH_CONFLICT`. PATCH must not silently overwrite another tab's saved draft changes.

`params` is the full current editable parameter value map. It replaces `ModelDraftNode.params`; it is not a partial merge. Missing required editable_schema fields are validation-blocking.

### 5.4 Validate Draft

```http
POST /pipeline-drafts/{draft_id}/validate
```

Request:

```ts
{
  execution_mode?: "rerun_child" | "new_run";
}
```

If omitted, `execution_mode` defaults to `draft.default_execution_mode`. The UI must send `"rerun_child"` in v1.6.4.

Response:

```ts
type DraftValidationResult = {
  ok: boolean;
  status: "valid" | "invalid" | "blocked";
  executable: boolean;
  checks: Array<{
    code: string;
    level: "error" | "warning" | "info";
    message: string;
    node_id?: string;
    blocking: boolean;
  }>;
  resolved_execution: {
    execution_mode: "rerun_child" | "new_run";
    compare_source_available: boolean;
    rerun_from_run_id?: string;
    rerun_from_model_node_id?: string;
    rerun_from_op_node_id?: string;
  };
  validated_execution_mode?: "rerun_child" | "new_run";
  validated_draft_hash?: string;
  validated_at: string;
};
```

Behavior:

```text
load draft
compute current draft_hash
resolve request.execution_mode or draft.default_execution_mode
validate draft schema version
validate InputNode -> ModelNode graph shape
validate input binding / input_fingerprint
validate created_from source run/node context
validate ModelDraftNode.source_ref matches PipelineDraft.created_from
validate editable_schema params
validate execution_mode
```

For `execution_mode = "rerun_child"`:

```text
require created_from
require source input still matches InputNode input_fingerprint
require Compare source available
```

For `execution_mode = "new_run"`:

```text
return blocked with NEW_RUN_EXECUTION_NOT_ENABLED
```

`validated_draft_hash` and `validated_execution_mode` are returned only when validation is successful and `executable = true`. Non-blocking warnings stay in `checks[]` with `level = "warning"`; they do not change `status` away from `"valid"`.
Validate Draft must not run the model, create artifacts, perform dry-run execution, or schedule execution.

### 5.5 Execute Draft

```http
POST /pipeline-drafts/{draft_id}/execute
```

Request:

```ts
{
  validated_draft_hash: string;
  execution_mode: "rerun_child" | "new_run";
  idempotency_key?: string;
}
```

Behavior:

```text
reject execution_mode = new_run with NEW_RUN_EXECUTION_NOT_ENABLED
load draft
recompute current draft_hash
require current draft_hash == request.validated_draft_hash
acquire draft execution lock
reload draft
recompute current draft_hash again
require current draft_hash == request.validated_draft_hash again
server-side revalidate draft using request.execution_mode
require validation executable = true
require request.execution_mode == validation.validated_execution_mode
dedupe by idempotency_key if provided, else by draft_id + validated_draft_hash + execution_mode
build frozen executed_pipeline_draft payload in memory
allocate child run id / create pending run record
write runs/{new_run_id}/executed_pipeline_draft.json
write pipeline_draft provenance into pending run metadata
delegate internally to existing rerun execution adapter
mark run visible / running / completed according to existing run lifecycle
return run_id + produced_lineage + focus / pending_index poll information
```

A run must not become visible as a comparable child until both `executed_pipeline_draft.json` and pipeline-draft provenance have been written.

Execute acquires the draft execution lock before final revalidation and snapshot freezing. After acquiring the lock, the server reloads the draft, recomputes `current_draft_hash`, requires it still equals `validated_draft_hash`, and then revalidates. This closes the race where another tab patches the draft between revalidation and snapshot freezing.

Duplicate execute semantics:

```text
same dedupe key while execution is pending:
  return the existing pending run_id with deduped = true

same dedupe key after a run has been created:
  return the existing run_id with deduped = true

same draft_id but different validated_draft_hash:
  allowed, because the executable draft content changed
```

`DRAFT_EXECUTION_IN_PROGRESS` and `DUPLICATE_DRAFT_EXECUTION` are reserved for cases where the server detects a duplicate but cannot safely resolve the existing run id.

Response:

```ts
type DraftExecutionResult = {
  ok: boolean;
  run_id: string;
  draft_id: string;
  executed_draft_hash: string;
  execution_mode: "rerun_child";
  deduped?: boolean;

  produced_lineage: {
    rerun_from_run_id: string;
    rerun_from_model_node_id: string;
    rerun_from_op_node_id: string;
  };

  focus: {
    status: "ready" | "pending_index";
    run_id: string;
    target_model_node_id?: string;
    poll?: {
      rerun_from_run_id: string;
      rerun_from_model_node_id: string;
      rerun_from_op_node_id: string;
    };
  };
};
```

### 5.6 Existing direct rerun API

`/runs/{run_id}/rerun` remains direct node rerun only.

It must not accept:

```text
draft_id
validated_draft_hash
executed_draft_hash
PipelineDraft graph payloads
```

## 6. UI / Interaction Design

### 6.1 Entry

```text
Canonical:
Lineage Detail -> eligible executed model node -> Open as Draft Graph

Shortcut:
Run Overview -> Open in Graph
only if exactly one eligible model node exists;
otherwise require explicit model node selection or route to Lineage.
```

Run-level shortcuts must not guess source model node, owner run, operation node, or input binding.

### 6.2 Route

```text
/pipeline-drafts/:draft_id
```

On page load:

```text
GET /pipeline-drafts/{draft_id}
render PipelineDraftV1
display current draft_hash
```

### 6.3 Layout

```text
Toolbar:
Draft title
Source run / source model node
Saved / unsaved / validation stale
Validate
Execute Draft

Canvas:
fixed InputNode -> ModelNode

Inspector:
selected node detail

Validation panel:
blocking errors / warnings / provenance summary
```

The canvas is a fixed graph view in v1.6.4. It is not a drag-drop DAG builder.

### 6.4 InputNode inspector

```text
read-only
source_type = run_input
run_input_id
input_fingerprint
schema_fingerprint
row_count / column_count
columns summary
status: bound / missing / invalid
```

InputNode cannot be edited in v1.6.4. There is no upload rebinding, dataset patch, cleaning, filtering, or schema mutation.

### 6.5 ModelNode inspector

```text
model_type
schema_id
source params
current params
editable_schema controls
changed fields summary
Reset to source
Save changes
```

`Save changes` calls:

```http
PATCH /pipeline-drafts/{draft_id}
```

with:

```ts
{
  model_node_id: string;
  base_draft_hash: string;
  params: Record<string, unknown>;
}
```

`Save changes` must send the latest `draft_hash` returned by `GET /pipeline-drafts/{draft_id}` or the previous successful `PATCH` as `base_draft_hash`. If PATCH returns `DRAFT_HASH_CONFLICT`, the UI reloads the draft and marks local edits conflicted or stale.

The endpoint replaces only `ModelDraftNode.params`.

### 6.6 Draft state model

```text
saved:
  server draft matches current UI state

unsaved:
  user has local edits not yet persisted by PATCH

validation stale:
  server draft changed after last successful validation;
  current draft_hash != validated_draft_hash

valid:
  latest server draft has successful Validate result;
  current draft_hash == validated_draft_hash
```

Validate Draft validates the server-stored draft, not unsaved local editor state.
v1.6.4 uses the safer behavior: Validate is disabled until Save changes succeeds. It does not auto-save before validation.

Button states:

```text
Initial:
Validate enabled if draft is saved
Execute disabled

Unsaved local edits:
Save changes enabled
Validate disabled
Execute disabled

Saved but not validated:
Validate enabled
Execute disabled

Validate OK:
Execute enabled only when current_draft_hash == validated_draft_hash

Any saved edit after validation:
validation stale
Execute disabled
Validate enabled

Validate failed:
Execute disabled
show blocking checks
```

Execute sends the current `validated_draft_hash`.

### 6.7 Execute success

If `focus.status = "ready"`:

```text
navigate to /runs/{run_id}?focus=target_model_node_id
or equivalent lineage focus route
```

If `focus.status = "pending_index"`:

```text
navigate to run/lineage
poll using focus.poll:
  rerun_from_run_id
  rerun_from_model_node_id
  rerun_from_op_node_id
```

The UI must not require a target model node id before the child run has been indexed.

### 6.8 Out of scope UI

```text
drag-drop
node palette
adding/deleting edges
transform/clean nodes
new upload path
execution mode picker
new_run button
draft library
AI graph generation
```

## 7. Validation, Errors, and Gates

### 7.1 Validation layers

```text
1. Draft schema
2. Graph shape
3. Input binding
4. Source context / provenance
5. Model params / editable_schema
6. Execution mode / lineage eligibility
7. Compare-source readiness
```

### 7.2 Blocking codes

```text
UNSUPPORTED_DRAFT_SCHEMA_VERSION
INVALID_DRAFT_GRAPH_SHAPE
UNKNOWN_DRAFT_NODE_TYPE
MISSING_INPUT_NODE
MISSING_MODEL_NODE
INVALID_DRAFT_EDGE

INPUT_BINDING_MISSING
INPUT_FINGERPRINT_MISMATCH
INPUT_SCHEMA_FINGERPRINT_MISMATCH
REQUIRED_INPUT_COLUMN_MISSING

SOURCE_RUN_NOT_FOUND
SOURCE_MODEL_NODE_NOT_FOUND
SOURCE_OP_NODE_MISMATCH
SOURCE_NODE_HASH_MISMATCH
SOURCE_CONTEXT_FINGERPRINT_MISMATCH
CREATED_FROM_REQUIRED_FOR_RERUN_CHILD

MODEL_NODE_NOT_ELIGIBLE
MODEL_EDITABLE_SCHEMA_MISSING
MODEL_SOURCE_REF_MISMATCH
MODEL_SCHEMA_UNSUPPORTED
MODEL_EXECUTION_ADAPTER_UNAVAILABLE
MODEL_PARAMS_INVALID
MODEL_PARAM_COLUMN_NOT_FOUND
NON_EDITABLE_FIELD_PATCH

NEW_RUN_EXECUTION_NOT_ENABLED
VALIDATION_REQUIRED
VALIDATED_DRAFT_HASH_MISMATCH
DRAFT_HASH_CONFLICT
DRAFT_LOCKED_FOR_EXECUTION
DRAFT_EXECUTION_IN_PROGRESS
DUPLICATE_DRAFT_EXECUTION
COMPARE_SOURCE_UNAVAILABLE
```

For v1.6.4 `rerun_child`, `COMPARE_SOURCE_UNAVAILABLE` is blocking because Compare with source is part of the required product loop.

### 7.3 Validation result rules

`validated_draft_hash` appears only when:

```text
ok = true
status = "valid"
executable = true
no blocking checks
```

Non-blocking warnings are represented only as `checks[].level = "warning"` with `blocking = false`. There is no separate `"warning"` validation status in v1.6.4.

`new_run` returns:

```text
ok = false
status = "blocked"
executable = false
code = NEW_RUN_EXECUTION_NOT_ENABLED
validated_draft_hash omitted
```

Validate Draft must not:

```text
run the model
create artifacts
schedule execution
perform dry-run execution
```

### 7.4 Execute error status

```text
400:
malformed request

404:
draft not found

409:
VALIDATION_REQUIRED
VALIDATED_DRAFT_HASH_MISMATCH
NEW_RUN_EXECUTION_NOT_ENABLED
DRAFT_HASH_CONFLICT
DRAFT_LOCKED_FOR_EXECUTION
DRAFT_EXECUTION_IN_PROGRESS
DUPLICATE_DRAFT_EXECUTION
SOURCE_RUN_NOT_FOUND
SOURCE_MODEL_NODE_NOT_FOUND
SOURCE_OP_NODE_MISMATCH
SOURCE_NODE_HASH_MISMATCH
SOURCE_CONTEXT_FINGERPRINT_MISMATCH
INPUT_FINGERPRINT_MISMATCH
INPUT_SCHEMA_FINGERPRINT_MISMATCH
COMPARE_SOURCE_UNAVAILABLE

422:
UNSUPPORTED_DRAFT_SCHEMA_VERSION
INVALID_DRAFT_GRAPH_SHAPE
UNKNOWN_DRAFT_NODE_TYPE
MISSING_INPUT_NODE
MISSING_MODEL_NODE
INVALID_DRAFT_EDGE
MODEL_PARAMS_INVALID
MODEL_PARAM_COLUMN_NOT_FOUND
NON_EDITABLE_FIELD_PATCH
CREATED_FROM_REQUIRED_FOR_RERUN_CHILD
MODEL_SCHEMA_UNSUPPORTED
MODEL_EXECUTION_ADAPTER_UNAVAILABLE
```

`VALIDATION_REQUIRED` uses `409` in v1.6.4 to keep the status surface small.

## 8. Implementation Boundaries and Rollout

### 8.1 Ownership

```text
Backend owns:
- pipeline draft store
- atomic draft JSON read/write
- draft id generation and path safety
- canonical executable draft hash
- from-node eligibility resolution
- validate checks
- execute snapshot/provenance
- execute idempotency / double-submit protection
- delegation to existing rerun adapter

Frontend owns:
- Draft Graph route
- fixed InputNode -> ModelNode canvas
- controlled ModelNode params editing
- saved / unsaved / validation stale state
- validate / execute button gating
- focus / pending poll navigation

Existing rerun path owns:
- direct node rerun only
- no PipelineDraft request fields
```

Draft creation and editing must not mutate the source run directory or source run metadata.

### 8.2 Feature flags

```text
PIPELINE_DRAFTS_ENABLED = true for v1.6.4 rollout
NEW_RUN_EXECUTION_ENABLED = false
```

When `NEW_RUN_EXECUTION_ENABLED = false`:

```text
Validate returns blocked with NEW_RUN_EXECUTION_NOT_ENABLED
Execute rejects new_run with NEW_RUN_EXECUTION_NOT_ENABLED
```

### 8.3 Storage and execution safety

PipelineDraft JSON writes must be atomic:

```text
write temp file
fsync if available
rename into data/pipeline_drafts/{draft_id}.json
```

Draft hash must be computed from executable content only.

Execute Draft must protect against duplicate submits:

```text
same draft_id + validated_draft_hash must not accidentally create duplicate child runs through double-click or retry
```

PATCH and Execute use optimistic concurrency plus a short execution lock:

```text
PATCH requires base_draft_hash and returns DRAFT_HASH_CONFLICT on mismatch
PATCH returns DRAFT_LOCKED_FOR_EXECUTION if the draft is being frozen/executed
Execute locks draft_id while freezing snapshot and allocating the child run
```

The executed snapshot is immutable:

```text
runs/{new_run_id}/executed_pipeline_draft.json is written as provenance and not edited later
```

If execution fails before a child run is successfully created, the system must not leave a partially valid child run that appears comparable.

### 8.4 Worktree and branch

```text
New isolated worktree:
.worktrees/workbench-v1.6.4

Branch:
codex/workbench-v1.6.4

Base:
v1.6.3 / current origin/main at bc7a40f
```

### 8.5 Phased build gates

```text
v1.6.4-a: PipelineDraft data model + JSON store + hash

Gate:
  draft store tests
  draft_id path-safety tests
  atomic JSON write tests
  hash canonicalization tests
  no run directory mutation for mutable draft
```

```text
v1.6.4-b: from-node + GET/PATCH + validate APIs

Gate:
  fail-closed source tests
  graph shape tests
  editable_schema param tests
  GET returns draft + draft_hash
  PATCH only replaces ModelDraftNode.params
  PATCH requires base_draft_hash
  PATCH rejects stale base_draft_hash with DRAFT_HASH_CONFLICT
  PATCH params replace the full editable value map
  no dry-run validation tests
```

```text
v1.6.4-c: execute API + rerun_child integration

Gate:
  validated_draft_hash required
  stale hash rejected
  server-side revalidation required
  request.execution_mode must match validated_execution_mode
  new_run rejected with NEW_RUN_EXECUTION_NOT_ENABLED
  duplicate execute submit protected
  duplicate submit returns existing run_id with deduped = true when resolvable
  execution lock prevents PATCH during snapshot freezing
  lock acquired before final reload / hash check / revalidation
  executed snapshot written
  child run provenance written
  Compare source available
```

```text
v1.6.4-d: Draft Graph View

Gate:
  route loads
  fixed graph renders
  input read-only
  model params save via PATCH
  Validate disabled while unsaved
  Execute disabled until current hash is validated
  validation stale after saved edit
  pending_index poll uses produced_lineage
```

```text
v1.6.4-e: browser smoke + full gate

Gate:
  Lineage model node -> Open as Draft Graph
  Edit params -> Save -> Validate -> Execute
  child focus / pending poll
  Compare with source
  full scripts/gate.sh
```

### 8.6 Browser smoke

```text
Open existing run with eligible model node
Open Lineage Detail
Click Open as Draft Graph
Verify /pipeline-drafts/{draft_id}
Verify InputNode -> ModelNode visible
Verify InputNode is read-only
Edit one editable_schema field
Save changes
Validate
Execute
Verify child run focused or pending poll resolves
Verify Compare with source is available on child
Verify direct /runs/{run_id}/rerun still works for direct rerun path
```

### 8.7 Rollback behavior

If v1.6.4 is disabled:

```text
existing runs remain readable
existing direct rerun remains unchanged
saved PipelineDraft JSON files remain inert
Draft Graph entrypoints are hidden or disabled
POST /pipeline-drafts/from-node rejects
PATCH /pipeline-drafts/{draft_id} rejects
POST /pipeline-drafts/{draft_id}/validate rejects
POST /pipeline-drafts/{draft_id}/execute rejects
```

`GET /pipeline-drafts/{draft_id}` may either reject or remain read-only behind an explicit product decision. The simplest v1.6.4 rollback posture is that all `/pipeline-drafts` APIs reject except health or internal migration checks.

Rollback must not require deleting draft files or mutating existing run directories.

### 8.8 Release constraints

```text
No push / merge / tag without explicit authorization.
No cleanup of version worktree directory.
v1.6.4 worktree must be preserved after release.
```

### 8.9 Stop rules

If any of the following becomes necessary during implementation, stop and revisit the spec:

```text
transform/clean nodes
new uploaded dataset UI
new_run execution
mutable draft inside a run directory
/runs/{run_id}/rerun as the public draft execution API
source inference from run order / runs[0] / active head / timestamp similarity
unsaved local editor state executable by Validate or Execute
```

## 9. Tests and Gates

Backend focused tests:

```text
from-node fails closed on source_node_hash mismatch
from-node fails closed on source_context_fingerprint mismatch
from-node requires eligible model node
from-node requires editable_schema
from-node creates default_execution_mode = rerun_child
from-node does not guess source, owner, operation node, or input binding

GET returns draft + executable-content hash
draft_hash excludes volatile metadata
updated_at/status changes do not change draft_hash
params changes do change draft_hash
draft_id is server-generated and path-safe

PATCH only replaces ModelDraftNode.params
PATCH requires base_draft_hash
PATCH rejects stale base_draft_hash with DRAFT_HASH_CONFLICT
PATCH rejects mutation while Execute holds DRAFT_LOCKED_FOR_EXECUTION
PATCH params replace the full editable value map
PATCH rejects non-editable field mutation
PATCH rejects dataset patch
PATCH rejects code patch
PATCH rejects artifact patch
PATCH rejects params outside editable_schema type/enum/range rules

Validate passes only exact InputNode -> ModelNode shape
Validate blocks missing created_from for rerun_child
Validate checks InputNode input_fingerprint
Validate checks InputNode schema_fingerprint
Validate checks required model param columns exist in input schema
Validate blocks source_ref / created_from mismatch
Validate blocks new_run with NEW_RUN_EXECUTION_NOT_ENABLED
Validate binds validated_execution_mode to validated_draft_hash
Validate returns validated_draft_hash only when executable = true and status = valid
Validate warnings are non-blocking checks, not a separate status
Validate checks editable_schema_hash against the snapshotted schema
Validate checks schema_id maps to a supported execution adapter
Validate does not run model
Validate does not create artifacts
Validate does not schedule execution

Execute rejects new_run with NEW_RUN_EXECUTION_NOT_ENABLED
Execute rejects missing validation with VALIDATION_REQUIRED
Execute rejects stale validated_draft_hash
Execute rejects execution_mode different from validated_execution_mode
Execute revalidates server-side before running
Execute dedupes same draft_id + validated_draft_hash + execution_mode
Execute returns existing run_id with deduped = true for duplicate pending/completed submit
Execute locks draft during snapshot freezing
Execute lock is acquired before final reload, hash check, and revalidation
Execute writes snapshot and provenance before child is comparable
Execute writes executed_pipeline_draft snapshot
Execute records pipeline_draft provenance in new run metadata
Execute computes executed_draft_hash from frozen executable payload
Execute rerun_child produces child compare source
```

Frontend focused tests:

```text
Draft route loads via GET
InputNode inspector is read-only
ModelNode Save changes calls controlled PATCH
ModelNode Save changes sends base_draft_hash
ModelNode Save changes handles DRAFT_HASH_CONFLICT by reloading and marking edits stale/conflicted
Validate disabled while unsaved
Execute disabled until current hash is validated
Execute enabled only when saved and current_draft_hash == validated_draft_hash
Validation stale after saved edit
Validation panel shows blocking checks
Run Overview shortcut does not guess when multiple eligible nodes
Execute pending_index uses produced_lineage poll identifiers
Pending poll does not require target node id before indexing
```

Regression gates:

```text
No runs[0] fallback
No parent / active-head / timestamp / node_hash-similarity source inference
No PipelineDraft payload accepted by /runs/{run_id}/rerun
No draft_id / validated_draft_hash accepted by /runs/{run_id}/rerun
No transform/clean placeholder executable node
No local unsaved editor state executable by Validate or Execute
No arbitrary user-provided filesystem path accepted by PipelineDraft APIs
```

Full gate:

```bash
LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 bash ./scripts/gate.sh
```
