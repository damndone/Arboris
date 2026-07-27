# Frozen Context Pack

Line: `v1-8-3-cf4-execution-control-fence`
Baseline SHA: `6588e30b35dde7c5bf08fcfded12ad7d4338efa5`

## Objective
Implement the CF4 prerequisite execution-control primitive only. Add a generic
ExecutionControlStore that atomically compares caller-supplied subject cursors
and validity requirements, rejects stale, revoked, invalid, and expired
subjects without partial writes, allocates one monotonic control sequence, and
appends an immutable caller-provided control record. Cover synthetic
reservation ordering, revocation-before/after-CAS linearization, expected
revision conflicts, expiry, duplicate/idempotent records, and canonical
digests. Do not implement Run, PreparedRunIntent, DispatchReservation,
dispatcher, supervisor, process, network, HTTP, UI, or new automatic execution.

## Boundary
- Affected paths: `backend/workbench/capability_factory/control.py`, `tests/test_capability_factory_control.py`
- Allowed paths: `backend/workbench/capability_factory/control.py`, `tests/test_capability_factory_control.py`
- Protected paths: `backend/workbench/capability_factory/execution_authorization.py`, `backend/workbench/agent/notebook/service.py`, `backend/workbench/services/draft_service.py`, `backend/workbench/services/draft_materialization.py`, `backend/workbench/projects.py`, `backend/workbench/app.py`, `backend/workbench/agent/trace.py`, `backend/workbench/agent/context_compiler.py`, `frontend/src/notebook/NotebookSurface.tsx`, `frontend/src/notebook/notebook.css`
- Dependencies: `6588e30 provides deterministic caller-supplied materialization and Draft identities`, `CF1 control.py and tests provide the existing append-only per-namespace control baseline`
- Tests: `LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/pytest -q tests/test_capability_factory_control.py tests/test_capability_execution_authorization.py tests/test_notebook_materialization.py tests/test_pipeline_drafts_store.py tests/test_no_exercise_specific_naming.py`
- Known gates: `caller-supplied subject identities and control records must be path-safe, bounded, canonical, and deterministic`, `compare and append must be one serialized operation with no partial multi-subject write`, `revocation or expiry committed before compare causes rejection; reservation committed first remains historically valid`, `this line proves only control-plane semantics, not Run, dispatcher, supervisor, native containment, browser, full gate, or release`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
No matching completed retrospective was selected.
