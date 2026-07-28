# Frozen Context Pack

Line: `v1-8-3-cf4-dispatch-reservation-contract`
Baseline SHA: `3b9b95cea5cbcd9357851854587b0614b90f1b82`

## Objective
Add the immutable DispatchReservation@1.0 record contract and derive it only
from a PreparedRunIntent plus a durable control record snapshot. Bind
authorization identity, intent digest, caller-supplied attempt/run IDs, lease
epoch, executor idempotency key, control sequence, and exact subject cursors.
Reject mismatched or mutable input and support strict round-trip serialization.
Do not change authorization transitions, create Run directories, spawn a
process, add a supervisor, network, HTTP, UI, or automatic execution.

## Boundary
- Affected paths: `backend/workbench/capability_factory/dispatch.py`, `tests/test_capability_dispatch_contract.py`
- Allowed paths: `backend/workbench/capability_factory/dispatch.py`, `tests/test_capability_dispatch_contract.py`
- Protected paths: `backend/workbench/capability_factory/control.py`, `backend/workbench/capability_factory/control_store.py`, `backend/workbench/capability_factory/execution_authorization.py`, `backend/workbench/services/draft_service.py`, `backend/workbench/projects.py`, `backend/workbench/app.py`, `backend/workbench/agent/trace.py`, `backend/workbench/agent/context_compiler.py`, `frontend/src/notebook/NotebookSurface.tsx`, `frontend/src/notebook/notebook.css`
- Dependencies: `3b9b95c provides the immutable PreparedRunIntent identity contract`, `ad9e7e8 provides restart-stable durable control records and subject snapshots`
- Tests: `LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/pytest -q tests/test_capability_dispatch_contract.py tests/test_capability_factory_control_store.py tests/test_capability_execution_authorization.py tests/test_no_exercise_specific_naming.py`
- Known gates: `reservation must bind the exact intent digest, authorization identity, attempt/run IDs, lease epoch, executor key, control sequence, and subject snapshot`, `strict round-trip and tamper rejection; no caller-controlled control sequence or unbound identity`, `this line proves only reservation record semantics, not authorization transition, Run, spawn, supervisor, containment, browser, full gate, or release`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
No matching completed retrospective was selected.
