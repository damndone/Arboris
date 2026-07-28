# Frozen Context Pack

Line: `v1-8-3-mem1-project-context-index`
Baseline SHA: `8bdacd3a7cc2ec6ab81c85bff1bb31a05c8b2389`

## Objective
Implement MEM1 as a rebuildable, content-addressed Project/RunFamily context index and pure context projection. Define bounded immutable index revisions that reference canonical source manifests and revision/hash cursors without copying raw datasets or unbounded artifacts; build only from caller-supplied canonical source facts; persist and reload append-only revisions with deterministic idempotency; reject stale or malformed inputs; and expose omission/truncation provenance in the projection. Declare package-local trace payload contracts only. The slice must not edit the shared Context Compiler, app startup, Notebook surface, capability ranking/admission, authorization, or dispatch paths, and memory must remain default-off and non-authoritative.

## Boundary
- Affected paths: `backend/workbench/domain_memory/__init__.py`, `backend/workbench/domain_memory/project_index_contract.py`, `backend/workbench/domain_memory/project_index_store.py`, `backend/workbench/domain_memory/project_index_builder.py`, `backend/workbench/domain_memory/context_projection.py`, `backend/workbench/domain_memory/trace_contracts.py`, `tests/test_project_memory_contract.py`, `tests/test_project_memory_store.py`, `tests/test_project_memory_builder.py`, `tests/test_project_memory_context_projection.py`, `tests/test_project_memory_trace.py`
- Allowed paths: `backend/workbench/domain_memory/__init__.py`, `backend/workbench/domain_memory/project_index_contract.py`, `backend/workbench/domain_memory/project_index_store.py`, `backend/workbench/domain_memory/project_index_builder.py`, `backend/workbench/domain_memory/context_projection.py`, `backend/workbench/domain_memory/trace_contracts.py`, `tests/test_project_memory_contract.py`, `tests/test_project_memory_store.py`, `tests/test_project_memory_builder.py`, `tests/test_project_memory_context_projection.py`, `tests/test_project_memory_trace.py`
- Protected paths: `backend/workbench/agent/context_compiler.py`, `backend/workbench/agent/trace.py`, `backend/workbench/app.py`, `backend/workbench/capability_factory/execution_authorization.py`, `backend/workbench/capability_factory/dispatch.py`, `frontend/src/notebook/NotebookSurface.tsx`, `frontend/src/notebook/notebook.css`
- Dependencies: `8bdacd3a7cc2ec6ab81c85bff1bb31a05c8b2389`
- Tests: `LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/pytest -q tests/test_project_memory_contract.py tests/test_project_memory_store.py tests/test_project_memory_builder.py tests/test_project_memory_context_projection.py tests/test_project_memory_trace.py tests/test_no_exercise_specific_naming.py`
- Known gates: `Pure projection only; no shared Context Compiler or app/UI mounting`, `Memory remains non-authoritative and default-off`, `No raw dataset copy, unbounded artifact copy, network, or execution`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
No matching completed retrospective was selected.
