# Frozen Context Pack

Line: `v1-8-3-cf4-durable-binding-registry`
Baseline SHA: `1263a3abf0fa6bd38af4d309bb3089d9d375e898`

## Objective
Implement the missing durable CapabilityBindingCatalog registry seam. Add an
FD-bound append-only index that persists only capability id, immutable binding
digest, and the bounded Agent planner projection; never persist executable
entrypoints, raw datasets, or binding internals. Provide a
DurableCapabilityBindingCatalog compatible with the existing NotebookService
catalog type. Registration must validate through the existing server-owned
catalog before durable append, be idempotent for the same identity, reject
rebinds and malformed journals fail-closed, and restore only through a
caller-supplied trusted binding loader that re-verifies the binding. Keep
execution authorization and process dispatch untouched; this slice only makes
the existing recommendation/service lookup restart-recoverable.

## Boundary
- Affected paths: `backend/workbench/capability_factory/binding_registry.py`, `tests/test_capability_binding_registry.py`
- Allowed paths: `backend/workbench/capability_factory/binding_registry.py`, `tests/test_capability_binding_registry.py`
- Protected paths: `backend/workbench/capability_factory/notebook_catalog.py`, `backend/workbench/agent/notebook/service.py`, `backend/workbench/http/notebook_routes.py`, `backend/workbench/app.py`, `backend/workbench/capability_factory/execution_authorization.py`, `backend/workbench/capability_factory/dispatch.py`, `frontend/src/notebook/NotebookSurface.tsx`, `frontend/src/notebook/notebook.css`
- Dependencies: none
- Tests: `LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/pytest -q tests/test_capability_binding_registry.py tests/test_notebook_capability_binding.py tests/test_capability_notebook_binding.py tests/test_no_exercise_specific_naming.py`
- Known gates: `FD-bound append-only registry: no raw path writer, no symlink traversal, malformed journal fails closed`, `registry persists only binding identity and bounded planner projection; no entrypoint, raw data, or automatic execution`, `restore requires a trusted binding loader and existing NotebookService catalog compatibility`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
No matching completed retrospective was selected.
