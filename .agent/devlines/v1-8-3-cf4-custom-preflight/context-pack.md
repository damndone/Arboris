# Frozen Context Pack

Line: `v1-8-3-cf4-custom-preflight`
Baseline SHA: `9c5cfbf6e13a941be35d1dc21fdead4d852861ed`

## Objective
Add a generic CF4 custom-capability dispatch preflight contract. It must join one PreparedRunIntent, one CapabilityResolutionBinding, one AdapterContract, and one exact ImplementationRevision; validate operation and consumer admission with explicit consumer support; emit a content-addressed plan that still requires user confirmation and a later DispatchReservation; and expose no runner, process, network, filesystem, or automatic execution method. Reject stale or mismatched identity joins before any external side effect.

## Boundary
- Affected paths: `backend/workbench/capability_factory/custom_dispatcher.py`, `tests/test_capability_custom_dispatcher.py`
- Allowed paths: `backend/workbench/capability_factory/custom_dispatcher.py`, `tests/test_capability_custom_dispatcher.py`
- Protected paths: `backend/workbench/capability_factory/execution_authorization.py`, `backend/workbench/capability_factory/dispatch.py`, `backend/workbench/capability_factory/notebook_binding.py`, `backend/workbench/capability_factory/adapter_contract.py`, `backend/workbench/app.py`, `backend/workbench/agent/trace.py`, `backend/workbench/agent/context_compiler.py`, `frontend/src/notebook/NotebookSurface.tsx`, `frontend/src/notebook/notebook.css`
- Dependencies: `9c5cfbf6e13a941be35d1dc21fdead4d852861ed`
- Tests: `LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/pytest -q tests/test_capability_custom_dispatcher.py tests/test_capability_dispatch_contract.py tests/test_capability_notebook_binding.py tests/test_capability_admission_contract.py tests/test_no_exercise_specific_naming.py`
- Known gates: `Preflight has no runner, spawn, network, host filesystem, or automatic execution surface`, `Consumer support is explicit and null never inherits semantics`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
No matching completed retrospective was selected.
