# Frozen Context Pack

Line: `v1-8-3-cf4-prepared-run-intent`
Baseline SHA: `ad9e7e8a20d306475ad34309498662560b6f0767`

## Objective
Implement the immutable PreparedRunIntent@1.0 contract for the CF4 seam.
The intent must content-address a validated Draft identity, exact capability
binding and validity revisions, operation, run id, input fingerprint, runtime
policy, namespace derivation and producer/ABI revisions. Enforce bounded
path-safe caller identities, strict field sets, canonical timestamps only when
needed, digest validation, immutable snapshots, and round-trip serialization.
This line prepares no Run fact or directory and adds no dispatcher, process,
network, HTTP, UI, or automatic execution behavior.

## Boundary
- Affected paths: `backend/workbench/capability_factory/dispatch.py`, `tests/test_capability_dispatch_contract.py`
- Allowed paths: `backend/workbench/capability_factory/dispatch.py`, `tests/test_capability_dispatch_contract.py`
- Protected paths: `backend/workbench/capability_factory/control.py`, `backend/workbench/capability_factory/control_store.py`, `backend/workbench/capability_factory/execution_authorization.py`, `backend/workbench/services/draft_service.py`, `backend/workbench/projects.py`, `backend/workbench/app.py`, `backend/workbench/agent/trace.py`, `backend/workbench/agent/context_compiler.py`, `frontend/src/notebook/NotebookSurface.tsx`, `frontend/src/notebook/notebook.css`
- Dependencies: `ad9e7e8 provides restart-stable durable control persistence`, `6588e30 provides deterministic Draft and materialization identities`, `capability binding and Notebook receipt contracts pin exact capability validity references`
- Tests: `LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/pytest -q tests/test_capability_dispatch_contract.py tests/test_capability_factory_control_store.py tests/test_capability_execution_authorization.py tests/test_notebook_materialization.py tests/test_pipeline_drafts_store.py tests/test_no_exercise_specific_naming.py`
- Known gates: `intent identity must include exact Draft, binding, operation, input, policy, namespace and producer revisions`, `from_dict rejects unknown/missing fields, invalid digests, paths, namespaces, revisions, and mutable caller input`, `preparation is pure and creates no Run directory, process, network, or dispatcher behavior`, `this line proves only PreparedRunIntent contract semantics, not reservation, supervisor, containment, browser, full gate, or release`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
No matching completed retrospective was selected.
