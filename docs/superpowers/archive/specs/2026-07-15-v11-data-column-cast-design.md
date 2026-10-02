# V11 Data-layer Typed Operations — `data.column.cast`

## Status

Approved implementation slice for the first V11 data-layer vertical path.
This slice is deliberately narrower than a general data editor and does not
expand the Main Agent or multi-operation planning surface.

## Goal

Allow a user to preview and confirm one constrained column dtype cast from a
real graph data node. Confirmation must create an immutable child data artifact
and child graph node, preserve the source artifact, record a typed operation,
and be recoverable through the existing operation lifecycle.

## Product boundary

The first operation is `data.column.cast`.

- The source is a graph `dataset_stage` node with a resolvable artifact.
- The column must already exist in the source tabular artifact.
- The target dtype is one of `numeric`, `string`, or `datetime`.
- Conversion is strict: any non-null source value that cannot be converted is
  a blocking preview error; confirmation is rejected while blocking errors
  exist.
- The source file and source graph node are never overwritten.
- The operation creates no downstream model run automatically.
- An Agent may inspect this capability later, but this slice exposes the same
  typed spec through a manual preview/confirm API first. Natural-language
  proposal generation is explicitly out of scope for this slice.

## Domain contract

### Typed spec

`DataColumnCastSpecV1` is frozen and JSON-safe:

```text
operation_id: data.column.cast
operation_version: v1
source_run_id: string
source_node_id: string
source_artifact_id: string
column: string
target_dtype: numeric | string | datetime
```

The source node, artifact id, and source SHA-256 are resolved by the backend;
the client cannot submit an arbitrary path or expression.

### Preview

`preview_data_column_cast` reads the source artifact through the existing
artifact index/path validation boundary and returns:

- source run/node/artifact and source SHA-256;
- column;
- before and after dtype;
- row count;
- successful conversion count;
- failure count and bounded failure examples;
- new missing-value count;
- deterministic source/result schema fingerprints;
- downstream invalidation summary;
- a blocking/non-blocking status.

The preview result is deterministic for the same source SHA, column, and
target dtype. It is not a mutation and does not create `workbench/` metadata.

### Effect

The lifecycle execution key is derived from the canonical spec and source
fingerprint. The effect writer:

1. revalidates the source node and artifact SHA;
2. reuses an existing effect for the same execution key;
3. writes a new CSV artifact under the source run's `derived/` directory;
4. registers it through `register_artifact` with the source artifact as input;
5. writes a JSON recipe/schema payload beside the artifact;
6. creates one child `dataset_stage` node and one `data.column.cast` edge in
   the same GraphStore run;
7. binds `artifact_id`, `child_node_id`, and `execution_key` to the Operation
   Record;
8. marks downstream model nodes as requiring revalidation through node
   annotations/summary, without rerunning them.

The source artifact remains byte-for-byte unchanged. The child id and artifact
id are deterministic functions of the execution key, so reconcile finds the
existing effect rather than creating another child.

## HTTP contract

The manual typed surface is project-scoped:

```text
POST /data-operations/column-cast/preview
POST /data-operations/column-cast/confirm
GET  /data-operations/column-cast/{operation_id}
```

Preview and confirm accept only the typed spec fields. Confirm accepts the
preview fingerprint and requires it to match a fresh preview before it enters
the shared `WorkbenchOperationLifecycle`. A stale source, changed artifact,
changed graph node, or changed preview fails closed with a conflict and makes
no mutation.

## Graph and audit semantics

The child node uses `NodeKind.DATASET_STAGE`, `Stage.TRANSFORM`, and a payload
reference to the immutable recipe/schema JSON. The edge operation is
`data.column.cast` and includes only JSON-safe typed parameters. The operation
record answers actor, confirmation source, source context, typed changes,
execution key, artifact binding, source/result fingerprints, and verification.

## Reliability boundary

The operation uses the existing single-worker lifecycle and its failpoints.
The effect is committed before diff/verification projection. A crash after
artifact creation or graph commit is reconciled by the deterministic execution
key. Multi-worker control-plane safety remains unsupported and is reported by
the system capability boundary.

## Acceptance evidence

- unit tests cover strict conversion, deterministic fingerprints, blocking
  failures, immutable source, provenance, and duplicate effect idempotency;
- lifecycle tests cover effect/binding/graph-commit crash recovery;
- API tests cover preview, stale confirm, confirm, reload/readback, and
  unsupported paths;
- frontend tests cover preview and explicit confirm state;
- a fresh browser smoke records URL, preview, confirm, child node/artifact,
  operation record, and reload recovery;
- the existing backend, golden, frontend, TypeScript, and diff checks pass.
