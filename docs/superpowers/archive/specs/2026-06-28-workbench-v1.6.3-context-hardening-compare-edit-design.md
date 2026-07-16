# Workbench v1.6.3: Context Hardening + Compare/Edit

Subtitle: rerun child-centered, explicit-source, summary-compare, single-node manual patch loop

## 1. Core Direction

Workbench v1.6.3 builds on v1.6.2 `NodeOperationContext v1`.

The release goal is to make a previously rerun child node understandable, comparable, manually adjustable, and safely rerunnable without introducing PipelineDraft, graph editing, AI actions, or arbitrary compare.

The primary user path is:

```text
Open rerun child node
-> Compare with explicit source
-> Review summary-level differences
-> Manually patch editable_schema fields
-> Preview patch
-> Confirm rerun
-> Focus new child, or pending-focus poll if focus is not indexed yet
-> Compare new child with source
```

This version is deliberately child-centered. The release demo starts from a child node that was produced by a context-driven rerun. It does not start from active-head auto recommendation, parent inference, shared-node owner choice, or arbitrary node compare.

v1.6.3 has three internal phases:

```text
v1.6.3-a: Context hardening and acceptance telemetry
v1.6.3-b: Compare with source v1
v1.6.3-c: Manual edit / rerun patch v1
```

These are engineering stages, not separate product versions. The release ships only after the full child-centered loop passes focused tests, browser regression, and the full gate.

## 2. Definitions

### 2.1 Source

In v1.6.3, `source` has one narrow meaning:

```text
source = the explicit rerun_from provenance recorded when the current child node was produced
```

Source must never be inferred from:

- parent run
- active head
- timestamp proximity
- node hash similarity
- run ordering
- `runs[0]`

Other compare labels may exist in the future, but they are semantically different:

```text
Compare with source = compare against explicit rerun_from provenance
Compare with parent = compare against graph/tree parent relationship
Compare with active head = compare against the current branch head
```

v1.6.3 implements `Compare with source` only. Parent compare and active-head compare are future slots and must not be used as fallback behavior.

### 2.2 Current Child

The current child is the selected executed lineage node whose `NodeOperationContextV1` resolves successfully and whose run/node provenance can be tied back to a context-driven rerun source.

### 2.3 Compare/Edit Loop

The loop is:

```text
child context
-> explicit source context
-> summary compare
-> schema-declared patch
-> context-validated rerun
-> new child context
-> summary compare
```

Every step is fail-closed. Missing source provenance disables the source compare path instead of guessing.

## 3. Rerun Provenance Model

v1.6.3 uses two levels of rerun provenance with different responsibilities:

```text
run-level rerun_from = audit / request provenance
node-level rerun_from = UI compare / node semantic provenance
```

They are not equal sources of truth.

`node-level rerun_from` is the long-term UI source of truth for `Compare with source`. `run-level rerun_from` records where the rerun request originated and supports audit, debugging, and a restricted transitional fallback.

### 3.1 Run-level RerunFrom

```ts
type RunRerunFrom = {
  owner_run_id: string;
  op_node_id: string;
  node_hash: string;
  context_fingerprint: string;
  patch_id?: string;
  rerun_request_id: string;
};
```

Run-level provenance must be persisted on the child run created by context-driven rerun.

It means:

```text
This child run was requested from this source context.
```

It does not mean:

```text
Every node in this child run can compare with that source node.
```

### 3.2 Node-level RerunFrom

```ts
type NodeRerunFrom = {
  owner_run_id: string;
  op_node_id: string;
  node_hash: string;
  context_fingerprint: string;
  patch_id?: string;
  rerun_request_id: string;
};
```

Node-level provenance belongs to the produced child node:

```ts
type LineageNode = {
  op_node_id: string;
  node_hash: string;
  node_index: number;
  forest_node_key: string;
  rerun_from?: NodeRerunFrom;
};
```

It means:

```text
This specific produced node came from this source node context.
```

### 3.3 Produced Node Lineage

Rerun success responses should expose enough produced-node lineage for the frontend to resolve and later re-resolve the new child:

```ts
type ProducedNodeLineage = {
  produced_owner_run_id: string;
  produced_op_node_id?: string;
  produced_node_hash?: string;
  rerun_request_id: string;
  rerun_from: RunRerunFrom;
  status: "indexed" | "pending_index";
};
```

This is required even when the backend returns `focus: null` because async child indexing has not finished.

### 3.4 Provenance Consistency Rules

1. If node-level `rerun_from` exists, it wins.
2. If node-level and run-level `rerun_from` disagree, fail closed.
3. On disagreement, do not show `Compare with source`.
4. On disagreement, record `lineage_mismatch` telemetry with mismatch fields.
5. Run-level fallback is transitional and must not become the long-term UI source of truth.
6. Run-level fallback must emit telemetry: `RUN_LEVEL_RERUN_FROM_FALLBACK`.
7. No fallback may infer source from parent, active head, timestamps, node hash similarity, run order, or `runs[0]`.

### 3.5 Transitional Run-level Fallback

v1.6.3 may allow a restricted fallback from run-level provenance only when all conditions are true:

- current node has no node-level `rerun_from`
- child run has run-level `rerun_from`
- the run was produced by context-driven rerun
- the run has exactly one produced focus node for that rerun request, or the backend can uniquely map `rerun_request_id` to the produced node
- produced node `op_node_id` and `node_hash` match the current selected node
- source context can be revalidated
- source `node_hash` and `context_fingerprint` match current persisted source metadata

If any condition fails, do not show `Compare with source`.

## 4. Compare With Source Gate

The `Compare with source` entry is visible only when the gate passes.

Show `Compare with source` only if:

1. `NodeOperationContextV1` resolves successfully for the current child node.
2. The current node has node-level `rerun_from`, or the restricted run-level fallback is uniquely resolvable.
3. `rerun_from.owner_run_id` exists.
4. `rerun_from.op_node_id` exists.
5. `rerun_from.node_hash` exists.
6. `rerun_from.context_fingerprint` exists.
7. The source context can be revalidated.
8. Source `node_hash` matches the persisted source node.
9. Source `context_fingerprint` matches the backend-recomputed context fingerprint.

Otherwise:

```text
Do not show Compare with source.
```

If the source `context_fingerprint` does not match the backend-recomputed context fingerprint, the gate fails with an explicit stale/mismatch result. Fingerprint mismatch is a failed gate result, not a successful compare state.

The UI may show a non-actionable explanation in diagnostics, such as:

```text
No rerun source recorded for this node.
```

But it must not show an actionable disabled compare button that implies a source exists but is unavailable.

## 5. Compare Operation Context

Compare v1 composes two successful `NodeOperationContextV1` objects:

```ts
type CompareWithSourceContextV1 = {
  compare_version: "compare-with-source/v1";
  compare_kind: "source";

  source: NodeOperationContextV1;
  current: NodeOperationContextV1;

  provenance: {
    source_kind: "node_level_rerun_from" | "run_level_rerun_from_fallback";
    rerun_request_id: string;
    patch_id?: string;
  };

  diagnostics: {
    warnings: string[];
    resolution_notes: string[];
  };
};
```

Compare must not reconstruct ownership, source, or lineage path directly from raw runs. It must use already-resolved contexts plus validated `rerun_from` provenance.

## 6. Compare Result Shape

Compare v1 is summary-level, section-based, and source-bound.

```ts
type CompareWithSourceResult = {
  compare_version: "compare-with-source/v1";
  compare_kind: "source";
  left: NodeOperationContextV1;
  right: NodeOperationContextV1;
  provenance: {
    source_kind: "node_level_rerun_from" | "run_level_rerun_from_fallback";
    rerun_request_id: string;
    patch_id?: string;
  };
  sections: {
    params: CompareSection<FieldDiff>;
    decisions: CompareSection<DecisionDiff>;
    metrics: CompareSection<FieldDiff>;
    diagnostics: CompareSection<DiagnosticDiff>;
    artifacts: CompareSection<ArtifactSummaryDiff>;
    upstream_path: CompareSection<UpstreamPathDiffSummary>;
  };
};

type CompareSection<T> = {
  changed: boolean;
  total_changed: number;
  items: T[];
  truncated?: boolean;
  summary: string;
};
```

Every section must support an empty state:

```ts
{
  changed: false,
  total_changed: 0,
  items: [],
  summary: "No metric changes detected."
}
```

Empty sections are not missing data. They mean no difference was detected for that section under Compare v1 rules.

For `upstream_path`, `items` should contain at most one `UpstreamPathDiffSummary` item. The section wrapper is kept for consistency with other sections and for uniform empty/truncated rendering.

### 6.1 FieldDiff

```ts
type FieldDiff = {
  field_id: string;
  label?: string;
  change_type: "added" | "removed" | "changed";
  old_value?: unknown;
  new_value?: unknown;
  delta?: number | string | null;
};
```

### 6.2 DecisionDiff

```ts
type DecisionDiff = {
  decision_id?: string;
  change_type: "added" | "removed" | "changed";
  label: string;
  old_value?: unknown;
  new_value?: unknown;
};
```

### 6.3 DiagnosticDiff

```ts
type DiagnosticDiff = {
  diagnostic_id?: string;
  change_type: "added" | "removed" | "level_changed" | "message_changed";
  old_level?: string;
  new_level?: string;
  old_message?: string;
  new_message?: string;
};
```

### 6.4 ArtifactSummaryDiff

```ts
type ArtifactSummaryDiff = {
  artifact_id?: string;
  name: string;
  change_type:
    | "added"
    | "removed"
    | "metadata_changed"
    | "summary_changed"
    | "preview_changed";
  old_summary?: string;
  new_summary?: string;
  changed_fields?: string[];
};
```

Artifact compare is metadata/summary only. Full artifact bodies, full reports, full datasets, binary content, and cell-level table diffs are out of scope.

### 6.5 UpstreamPathDiffSummary

```ts
type UpstreamPathDiffSummary = {
  change_type: "unchanged" | "length_changed" | "node_hash_changed" | "structure_changed";
  old_path_length: number;
  new_path_length: number;
  changed_node_count: number;
  summary: string;
};
```

Compare v1 does not render a full lineage-tree diff.

## 7. Compare UI

The UI should present section cards:

```text
Compare with source

Params changed
- model_type: linear -> logistic
- covariates: age,income -> age,income,gender

Metrics changed
- r_squared: 0.42 -> 0.51, delta +0.09

Diagnostics changed
- warning resolved: HIGH_MISSINGNESS
- new warning: SMALL_SAMPLE_SIZE

Artifacts changed
- table row count changed
- chart spec hash changed

Upstream path changed
- 1 upstream node hash changed
```

Default display limits:

- params: top 10 changed fields
- metrics: top 10 changed fields
- diagnostics: top 10 changes
- artifacts: top 5 summary changes
- upstream path: summary only

If a section is truncated, show:

```text
Showing N of M changes.
```

v1.6.3 does not need an expand-all mode.

## 8. Manual Rerun Patch

Manual patch v1 is:

```text
single-node, schema-declared, value-replacement patch
```

It can only modify fields exposed by the selected source node's current `editable_schema`.

```ts
type ManualRerunPatch = {
  patch_id: string;
  patch_source: "MANUAL_EDIT";
  source_context_fingerprint: string;
  editable_schema_version: string;

  target: {
    owner_run_id: string;
    op_node_id: string;
    node_hash: string;
  };

  changes: Array<{
    field_id: string;
    old_value: unknown;
    new_value: unknown;
  }>;
};
```

In the release demo, the patch target is the explicit source context behind the current child. The user opens the child, compares it with source, edits source-node `editable_schema` fields, and creates a new child from that source. The current child is not modified in place.

The current child may become a patch target only if the user starts a separate patch flow from that child after its own `NodeOperationContextV1` has been resolved and selected as the source for a new rerun. This is not the primary v1.6.3 demo path.

### 8.1 Patch Rules

1. `changes.length > 0`.
2. Duplicate `field_id` values are rejected.
3. `old_value !== new_value` after normalized comparison.
4. Each `field_id` must exist in current `editable_schema`.
5. Each `field_id` must be `editable: true`.
6. Hidden, internal, and read-only fields cannot be patched.
7. `old_value` must match the current source value.
8. `new_value` must pass type, range, enum, required, and custom validator checks.
9. `editable_schema_version` must match current source schema version.
10. Array and object fields are replaced as whole values.
11. Nested JSON patch, path patch, and partial array operations are not supported.
12. Patch cannot include code, artifact, dataset, downstream node, or run-level config changes.
13. Patch cannot target multiple nodes.
14. Patch cannot mutate historical source nodes in place.
15. A valid patch can only trigger context-driven rerun.

### 8.2 Normalized Comparison

Normalized comparison must be deterministic and schema-driven:

1. Numbers compare by numeric value after schema coercion.
2. Strings compare exactly, except fields declaring `trim: true` compare after schema-defined trimming.
3. Enums compare by canonical enum value.
4. Arrays compare by order-sensitive deep equality unless the schema declares `order_insensitive: true`.
5. Objects compare by canonical JSON serialization with sorted keys.
6. `undefined` and a missing field are distinct unless the schema declares default normalization.
7. `null` is distinct from `undefined` and from a missing field.
8. Schema coercion happens before `NOOP_PATCH` checks and before `FIELD_VALUE_STALE` checks.

### 8.3 Old Value as Precondition

`old_value` is a precondition check.

The backend does not trust the client as the source of truth. It compares `old_value` against the current persisted source value to detect stale UI edits.

If the value differs, return:

```text
FIELD_VALUE_STALE
```

The frontend should prompt:

```text
This parameter changed. Refresh the node and edit again.
```

### 8.4 Empty and No-op Patch

The backend rejects:

- empty `changes`
- changes where normalized `old_value` equals normalized `new_value`
- duplicate `field_id`
- changes that normalize to no effective difference after schema coercion

No-op reruns from manual patch are not part of v1.6.3.

### 8.5 Patch Submission Idempotency

`patch_id` is an idempotency key for manual rerun patch submission.

For the same project/user scope, same `source_context_fingerprint`, same target, same normalized changes, and same `patch_id`:

- if the first request already created a `rerun_request_id`, return the existing `rerun_request_id`
- if the first request already created a child run, return the existing rerun result when available
- do not create a duplicate child run

If the same `patch_id` is reused with a different source context, target, or normalized changes, reject:

```text
PATCH_ID_CONFLICT
```

The idempotency check must run before child run creation.

## 9. Patch Preview

Patch preview is mandatory before rerun.

The preview shows:

- source node label
- source owner run
- target `op_node_id`
- `editable_schema_version`
- changed fields
- `old_value`
- `new_value`
- validation status
- warning if run-level fallback provenance is being used

Patch preview must not show executable backend payloads as editable JSON. It is a confirmation surface, not an advanced payload editor.

In the primary v1.6.3 flow, the edit panel should be labeled as editing the explicit source node for a new sibling rerun, not editing the currently opened child in place.

Recommended confirm button text:

```text
Rerun source with changes
```

Avoid generic wording such as `Rerun with changes` because the user is currently viewing a child node.

## 10. Backend Validation

Manual patch rerun extends the v1.6.2 context-driven rerun validator. The backend validates both source context and patch.

Required checks:

1. `source_context_fingerprint` is still valid.
2. `target.owner_run_id` equals source context `owner_run_id`.
3. `target.op_node_id` equals source context `op_node_id`.
4. `target.node_hash` equals current source node hash.
5. `editable_schema_version` matches current source node schema.
6. Each `field_id` exists in editable schema.
7. Each `field_id` is editable.
8. Hidden, internal, and read-only fields are rejected.
9. `old_value` matches current source value.
10. `new_value` passes schema validation.
11. Patch does not contain code, artifact, dataset, downstream node, or run-level config changes.
12. Patch only targets one `op_node_id`.
13. Patch can only trigger rerun; it cannot mutate existing lineage.
14. The user is authorized to read the source context.
15. The user is authorized to read the current child context.
16. The user is authorized to create a rerun from the target source node.

Validation failures should be structured:

```ts
type ManualPatchValidationErrorCode =
  | "SOURCE_CONTEXT_STALE"
  | "SOURCE_CONTEXT_MISMATCH"
  | "EDITABLE_SCHEMA_STALE"
  | "FIELD_NOT_EDITABLE"
  | "FIELD_VALUE_STALE"
  | "INVALID_FIELD_VALUE"
  | "EMPTY_PATCH"
  | "NOOP_PATCH"
  | "DUPLICATE_FIELD"
  | "PATCH_ID_CONFLICT"
  | "UNSUPPORTED_PATCH_TARGET";
```

Frontend behavior:

- stop rerun
- refresh context if stale/mismatch
- preserve user-entered values only when safe
- require explicit retry after refresh
- do not auto-resubmit old patch

## 11. Context Hardening

v1.6.3 includes acceptance hardening needed before compare/edit becomes trustworthy.

### 11.1 Resolver Trace

Expose a deterministic resolver trace for successful and failed `NodeOperationContext` resolution:

- selected forest node key
- node hash
- active head run id
- candidate run refs
- selected run hint and source
- owner resolution
- context fingerprint inputs
- failure reason, if any

Trace is for debug and acceptance. It must not create alternate resolver semantics.

### 11.2 Context Fingerprint Logging

Log fingerprint validation inputs and result for write operations:

- request id
- operation
- owner run id
- op node id
- node hash
- forest node key
- active head run id
- submitted fingerprint
- recomputed fingerprint
- validation result
- mismatch fields

Logs must avoid full datasets, full artifacts, and large payload values.

### 11.3 Focus Null Telemetry

`focus: null` remains a valid degraded success when async child indexing has not produced a forest key yet.

Telemetry should record:

- rerun request id
- new run id
- rerun_from owner/op/node hash
- accepted context fingerprint
- pending focus start
- polling attempts
- final focus resolved / unresolved
- timeout reason, if any

The frontend must not guess focus from `runs[0]` or candidate array order.

### 11.4 Context Mismatch / Stale UX

For `context_mismatch` or `context_stale`:

1. Stop the operation.
2. Refresh forest and run metadata.
3. Re-resolve `NodeOperationContext`.
4. Show a clear stale-context message.
5. Require the user to retry manually.

The UI must not silently rebuild and resubmit the old payload.

### 11.5 Browser Regression Seed

Create a reproducible seed project for browser acceptance:

```text
source run
-> context-driven rerun child
-> child node has explicit rerun_from
-> child node can Compare with source
-> editable_schema field can be patched
-> patch rerun creates new child
-> new child focus resolves directly or through pending focus polling
-> new child can Compare with source
```

The seed must cover active head not being `runs[0]`.

### 11.6 Permanent runs[0] Regression

Add permanent regression tests proving:

- owner is not inferred from `runs[0]`
- source is not inferred from `runs[0]`
- focus is not inferred from `runs[0]`
- compare source is not inferred from `runs[0]`
- patch target is not inferred from `runs[0]`

## 12. Acceptance Demo

The release demo is:

```text
1. Open a rerun child node.
2. Confirm resolver trace identifies child owner and explicit rerun_from source.
3. Click Compare with source.
4. Review params, metrics, diagnostics, artifact summary, and upstream path summary diffs.
5. Edit one editable_schema field.
6. Preview patch with old/new values.
7. Confirm rerun.
8. Backend validates source context and patch.
9. New child run is created.
10. UI focuses new child, or uses focus:null pending polling until indexed.
11. Compare new child with source.
```

This demo must not require:

- active-head source recommendation
- parent compare
- arbitrary node compare
- shared-node manual owner selection
- AI
- PipelineDraft

## 13. Non-goals

v1.6.3 does not implement:

- active-head compare recommendation
- parent compare fallback
- latest child compare
- arbitrary two-node compare
- three-way compare
- side-by-side large diff editor
- full report text diff
- full dataset diff
- dataframe row/cell diff
- chart visual diff
- binary artifact diff
- full lineage tree diff
- AI patch
- AI automatic rerun
- AI action proposal
- custom code patch
- run-level patch
- multi-node patch
- nested JSON patch
- artifact patch
- dataset patch
- hidden/internal field patch
- historical node mutation
- PipelineDraft
- planned node edit
- graph node editor
- partial execution scheduler

## 14. Test Matrix

### 14.1 Compare Gate

| Scenario | Expected |
| --- | --- |
| current node has valid node-level `rerun_from` | show Compare with source |
| node-level missing, unique run-level fallback valid | show Compare with source and emit fallback telemetry |
| node-level missing, run-level ambiguous | do not show Compare with source |
| node-level and run-level disagree | do not show Compare with source; emit lineage mismatch |
| source context stale | do not compare; show stale context UX |
| source hash mismatch | do not compare; show mismatch UX |
| source fingerprint mismatch | do not compare; gate fails with stale/mismatch result |
| no `rerun_from` | do not show Compare with source |

### 14.2 Compare Result

| Section | Required behavior |
| --- | --- |
| params | added/removed/changed field diffs, top 10 |
| decisions | added/removed/changed summary |
| metrics | added/removed/changed field diffs with delta when available, top 10 |
| diagnostics | added/removed/level/message changes |
| artifacts | metadata/summary changes only, top 5 |
| upstream path | summary only |
| empty section | `changed=false`, `total_changed=0`, `items=[]`, clear summary |

### 14.3 Manual Patch

| Scenario | Expected |
| --- | --- |
| valid editable field change | preview then rerun allowed |
| empty changes | reject `EMPTY_PATCH` |
| no effective value change | reject `NOOP_PATCH` |
| duplicate field id | reject `DUPLICATE_FIELD` |
| repeated same `patch_id` with same payload | return existing `rerun_request_id` or rerun result; do not create duplicate child |
| repeated same `patch_id` with different payload | reject `PATCH_ID_CONFLICT` |
| unknown field id | reject `FIELD_NOT_EDITABLE` |
| read-only field | reject `FIELD_NOT_EDITABLE` |
| stale old value | reject `FIELD_VALUE_STALE` |
| stale schema version | reject `EDITABLE_SCHEMA_STALE` |
| invalid new value | reject `INVALID_FIELD_VALUE` |
| run-level patch | reject `UNSUPPORTED_PATCH_TARGET` |
| multi-node patch | reject `UNSUPPORTED_PATCH_TARGET` |

### 14.4 Rerun / Focus

| Scenario | Expected |
| --- | --- |
| patch rerun returns focus | reflect backend-updated active head and select new child |
| patch rerun returns `focus:null` | reflect backend-updated active head, start pending focus polling |
| produced lineage status is `pending_index` | keep produced op/node hash optional and poll by `rerun_request_id` |
| produced lineage status is `indexed` | use produced op/node hash for context re-resolution |
| pending focus resolves | select new child |
| pending focus times out | keep active head, show unresolved focus message |
| request fails before child creation | do not change active head |

## 15. Release Gates

Before release:

1. Context hardening tests pass.
2. Compare gate tests pass.
3. Compare result section tests pass.
4. Manual patch validator tests pass.
5. Patch preview UI tests pass.
6. Patch rerun backend tests pass.
7. Focus direct and `focus:null` pending tests pass.
8. Browser regression seed passes.
9. Permanent `runs[0]` regressions pass.
10. If Ask AI is visible in this build, it remains read-only and cannot submit patch or rerun actions.
11. Golden lineage outputs have no unreviewed drift.
12. Full gate passes:

```bash
LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 bash ./scripts/gate.sh
```

## 16. Future Work

After v1.6.3:

- parent compare can be introduced as its own explicit compare kind
- active-head compare recommendation can be introduced after source compare is stable
- node-level `rerun_from` should become the only UI source of truth before PipelineDraft work
- PipelineDraft can use stable node-level provenance to map draft nodes to materialized refs
- richer side-by-side diff viewers can be added after artifact/report/data diff semantics are separately specified
- Ask AI can explain compare results but must remain read-only until explicit action-proposal specs exist
