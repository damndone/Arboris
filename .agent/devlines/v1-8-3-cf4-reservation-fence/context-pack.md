# Frozen Context Pack

Line: `v1-8-3-cf4-reservation-fence`
Baseline SHA: `431c11a8a78d05cbb4b4f5cb6e15b1c46ec84f84`

## Objective
Add a typed dispatch reservation fence around the existing ExecutionControlStore. The fence must require one claimed authorization subject and the exact binding, host containment, bundle, evidence, and admission validity cursor revisions pinned by PreparedRunIntent before appending one dispatch_reservation record. It must derive the existing DispatchReservation from that single control-stream record, preserve idempotent retries after later revocation, and fail closed when any required subject is missing, stale, expired, or has the wrong status. Keep the slice pure control-plane: no authorization-journal transition, Draft, Run, process, supervisor, network, HTTP, UI, or automatic execution.

## Boundary
- Affected paths: `backend/workbench/capability_factory/dispatch.py`, `tests/test_capability_dispatch_contract.py`
- Allowed paths: `backend/workbench/capability_factory/dispatch.py`, `tests/test_capability_dispatch_contract.py`
- Protected paths: `backend/workbench/capability_factory/control.py`, `backend/workbench/capability_factory/control_store.py`, `backend/workbench/capability_factory/execution_authorization.py`, `backend/workbench/app.py`, `backend/workbench/agent/trace.py`, `backend/workbench/agent/context_compiler.py`, `frontend/src/notebook/NotebookSurface.tsx`, `frontend/src/notebook/notebook.css`
- Dependencies: `431c11a8a78d05cbb4b4f5cb6e15b1c46ec84f84`
- Tests: `LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/pytest -q tests/test_capability_dispatch_contract.py tests/test_capability_execution_authorization.py tests/test_capability_factory_control_store.py tests/test_capability_factory_control.py tests/test_no_exercise_specific_naming.py`
- Known gates: `Reservation uses only the serializable control fence; no cross-journal atomicity is claimed`, `No Draft/Run/process/network/HTTP/UI side effects in this line`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
No matching completed retrospective was selected.
