# Frozen Context Pack

Line: `v1-8-3-cf4-authorization-state-machine`
Baseline SHA: `e0226668a5c01c4e53eb3dba6c19d14b056222eb`

## Objective
Implement the CF4 authorization receipt state machine as an append-only, idempotent control-plane contract. Extend the existing OptionExecutionAuthorization snapshots and store with explicitly legal post-claim transitions for dispatch_reserved, running, dispatch_unknown, failed, and consumed; preserve the existing issued/rejected/claimed/invalidated behavior and stale-binding checks. Every transition must bind the prior receipt digest, authorization idempotency key, owner/lease epoch, and bounded transition metadata, reject illegal or replayed transitions, and be safe to retry after a process restart. This slice must not create a Draft, Run, Operation, process, supervisor, network request, or UI route, and must not claim atomicity across the separate control journal and authorization journal. Add focused contract tests and keep all existing execution authorization tests green.

## Boundary
- Affected paths: `backend/workbench/capability_factory/execution_authorization.py`, `tests/test_capability_execution_authorization.py`
- Allowed paths: `backend/workbench/capability_factory/execution_authorization.py`, `tests/test_capability_execution_authorization.py`
- Protected paths: `backend/workbench/app.py`, `backend/workbench/agent/trace.py`, `backend/workbench/agent/context_compiler.py`, `frontend/src/notebook/NotebookSurface.tsx`, `frontend/src/notebook/notebook.css`
- Dependencies: `e0226668a5c01c4e53eb3dba6c19d14b056222eb`
- Tests: `LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/pytest -q tests/test_capability_execution_authorization.py tests/test_capability_dispatch_contract.py tests/test_capability_factory_control_store.py tests/test_capability_factory_control.py tests/test_no_exercise_specific_naming.py`, `python -m compileall backend/workbench/capability_factory/execution_authorization.py`
- Known gates: `No Draft/Run/process/network/HTTP/UI side effects in this line`, `macOS native containment canary remains a host capability gate, not product evidence`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
No matching completed retrospective was selected.
