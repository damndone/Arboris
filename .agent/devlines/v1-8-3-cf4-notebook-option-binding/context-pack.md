# Frozen Context Pack

Line: `v1-8-3-cf4-notebook-option-binding`
Baseline SHA: `7fddf83f6043032a97ff7182e78bbbe289c87d93`

## Objective
# v1.8.3 CF4 Notebook Option binding contract slice

From the completed CF4 admission-control baseline, add the smallest typed bridge
from the existing CF1 `ResolutionBinding` plus CF3 adapter and CF4 assessment /
scoped admission records to a content-addressed `CapabilityResolutionBinding`.
Add the versioned `NotebookOptionRevision@1.2` wire contract that references that
binding and declares bounded execution modes, while keeping old 1.0/1.1 reads
unchanged. This slice is contract-only: it must not load or execute adapters,
create Graph/Draft/Run/Artifact records, register a workflow operation, or add a
new automatic execution surface. All cross-object identity, admitted-state,
runtime-policy, and binding freshness inputs must fail closed; only
`materialize_only` is available until the later execution-authorization slice.

## Boundary
- Affected paths: `backend/workbench/capability_factory/notebook_binding.py`, `backend/workbench/contracts/agent/notebook_option.py`, `tests/test_capability_notebook_binding.py`
- Allowed paths: `backend/workbench/capability_factory/notebook_binding.py`, `backend/workbench/contracts/agent/notebook_option.py`, `tests/test_capability_notebook_binding.py`
- Protected paths: `backend/workbench/agent/notebook/service.py`, `backend/workbench/agent/notebook/materialization.py`, `backend/workbench/agent/operations.py`, `backend/workbench/agent/agent_core.py`, `backend/workbench/graph`, `frontend/src`, `backend/workbench/capability_factory/admission_control.py`
- Dependencies: `.agent/devlines/v1-8-3-cf4-admission-control/RETROSPECTIVE.md`, `docs/superpowers/specs/v1.8.3/capability-factory-design.md`, `backend/workbench/capability_factory/contracts.py`, `backend/workbench/capability_factory/adapter_contract.py`
- Tests: `PYTHONPATH=backend .venv/bin/pytest -q tests/test_capability_notebook_binding.py tests/test_no_exercise_specific_naming.py`, `PYTHONPATH=backend .venv/bin/pytest -q tests/test_capability_factory_contracts.py tests/test_capability_adapter_contract.py tests/test_notebook_option_lifecycle.py`
- Known gates: `full scripts/gate.sh may remain blocked by host sandbox-exec sandbox_apply: Operation not permitted; do not classify as product regression`, `new worktrees require bash scripts/link-shared-deps.sh with an absolute path before valid gate claims`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
No matching completed retrospective was selected.
