# Frozen Context Pack

Line: `v1-8-3-cf4-supervisor-state-contract`
Baseline SHA: `ca2898442c95465df925c0257b2b0b32450740e8`

## Objective
Implement the CF4 durable-supervisor state contract for one reserved capability
attempt. Add only a strict, content-addressed execution-attempt record and an
independent AttemptQuiescenceProof/reconciliation contract. The slice must
bind reservation identity, executor idempotency key, lease epoch, and
process/job handle identity; reject stale epochs and replay mismatches; make
unknown dispatch terminal until an independently issued quiescence proof is
present; and remain execution-free (no spawn, subprocess, network, host
filesystem, VM, or automatic execution). Add focused tests for exact schemas,
round trips, state transitions, fencing, replay, proof outcomes, and the
absence of execution APIs. Do not modify authorization, dispatch, Notebook,
Agent, or containment seams in this line.

## Boundary
- Affected paths: `backend/workbench/capability_factory/supervisor.py`, `tests/test_capability_supervisor_contract.py`
- Allowed paths: `backend/workbench/capability_factory/supervisor.py`, `tests/test_capability_supervisor_contract.py`
- Protected paths: `backend/workbench/capability_factory/execution_authorization.py`, `backend/workbench/capability_factory/dispatch.py`, `backend/workbench/capability_factory/control.py`, `backend/workbench/capability_factory/control_store.py`, `backend/workbench/capability_factory/notebook_binding.py`, `backend/workbench/app.py`, `backend/workbench/agent/trace.py`, `backend/workbench/agent/context_compiler.py`, `frontend/src/notebook/NotebookSurface.tsx`, `frontend/src/notebook/notebook.css`
- Dependencies: none
- Tests: `LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/pytest -q tests/test_capability_supervisor_contract.py tests/test_capability_dispatch_contract.py tests/test_capability_authorization_contract.py tests/test_no_exercise_specific_naming.py`
- Known gates: `contract-only: no subprocess, spawn, network, host filesystem, VM, or automatic execution`, `unknown dispatch is terminal until independent quiescence proof; no automatic retry`, `must reject stale lease epochs and replay mismatches`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
No matching completed retrospective was selected.
