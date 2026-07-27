# Frozen Context Pack

Line: `v1-8-3-cf4-durable-control-stream`
Baseline SHA: `027addcc7104fc7bb0de681ddfe048175df884d1`

## Objective
Make the generic execution-control fence durable without adding a dispatch
consumer. Persist subject cursor publications and compare-and-append records
in one append-only JSONL journal protected by an inter-process file lock.
Reload and validate the journal before every state-changing operation, retain
monotonic control sequence and idempotency semantics across process restarts,
reject malformed or conflicting records, and preserve atomic multi-subject
compare behavior. Do not implement PreparedRunIntent, Run creation, process
spawn, supervisor, network, HTTP, UI, or any new automatic execution surface.

## Boundary
- Affected paths: `backend/workbench/capability_factory/control_store.py`, `tests/test_capability_factory_control_store.py`
- Allowed paths: `backend/workbench/capability_factory/control_store.py`, `tests/test_capability_factory_control_store.py`
- Protected paths: `backend/workbench/capability_factory/control.py`, `backend/workbench/capability_factory/execution_authorization.py`, `backend/workbench/capability_factory/dispatch.py`, `backend/workbench/services/draft_service.py`, `backend/workbench/projects.py`, `backend/workbench/app.py`, `backend/workbench/agent/trace.py`, `backend/workbench/agent/context_compiler.py`, `frontend/src/notebook/NotebookSurface.tsx`, `frontend/src/notebook/notebook.css`
- Dependencies: `027addc provides the generic in-process cursor fence and immutable control records`, `existing agent storage provides JSONL parsing and durable file-lock patterns`
- Tests: `LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/pytest -q tests/test_capability_factory_control_store.py tests/test_capability_factory_control.py tests/test_capability_execution_authorization.py tests/test_no_exercise_specific_naming.py`
- Known gates: `journal replay must be canonical, monotonic, fail-closed, and preserve immutable subject snapshots`, `read-check-append is protected by one inter-process lock; failed multi-subject comparison leaves no record`, `restart and a second store instance must reuse the same idempotency result rather than create a duplicate`, `this line proves durable control-plane semantics only, not PreparedRunIntent, Run, dispatcher, supervisor, containment, browser, full gate, or release`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
No matching completed retrospective was selected.
