# Frozen Context Pack

Line: `v1-8-3-cf4-binding-provenance`
Baseline SHA: `e4dc1586692837a62a41b4d34c99e27efd70acdb`

## Objective
Extend the capability-bound Notebook option chain so the immutable binding
reference survives materialization, the persisted Pipeline Draft provenance,
and typed Agent trace events. Add a backward-compatible
OptionMaterialization@1.1 successor while preserving native/unbound
OptionMaterialization@1.0 records. Revalidate the current server binding and
the materialization/Draft provenance before replay or downstream use; fail
closed on missing, stale, or mismatched binding references. This line is
control-plane and provenance-only: it must not add process, network, or
automatic execution behavior.

## Boundary
- Affected paths: `backend/workbench/contracts/agent/notebook_option.py`, `backend/workbench/agent/notebook/materialization.py`, `backend/workbench/agent/notebook/service.py`, `backend/workbench/agent/trace.py`, `tests/test_capability_binding_provenance.py`
- Allowed paths: `backend/workbench/contracts/agent/notebook_option.py`, `backend/workbench/agent/notebook/materialization.py`, `backend/workbench/agent/notebook/service.py`, `backend/workbench/agent/trace.py`, `tests/test_capability_binding_provenance.py`
- Protected paths: `backend/workbench/app.py`, `backend/workbench/agent/notebook/planning_agent.py`, `backend/workbench/agent/notebook/store.py`, `backend/workbench/http/notebook_routes.py`, `frontend/src/notebook/NotebookSurface.tsx`, `frontend/src/notebook/notebook.css`
- Dependencies: none
- Tests: `LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/pytest -q tests/test_capability_binding_provenance.py tests/test_notebook_materialization.py tests/test_notebook_trace_chain.py tests/contracts/test_v181_contract_lock.py tests/test_no_exercise_specific_naming.py`
- Known gates: `OptionMaterialization@1.0 remains readable for native/unbound records; bound options use the V1.1 successor with the same current binding digest`, `Materialization replay and Draft provenance fail closed on missing or stale binding; trace carries only immutable binding identity and no execution grant`, `This line adds no process, network, host inspection, or automatic execution surface`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
No matching completed retrospective was selected.
