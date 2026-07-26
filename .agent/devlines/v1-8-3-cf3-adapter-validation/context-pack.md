# Frozen Context Pack

Line: `v1-8-3-cf3-adapter-validation`
Baseline SHA: `03e74404bbc5075a3306db24136c50a87c682be3`

## Objective
# v1.8.3 CF3 adapter and validation contract foundation

Implement the first bounded CF3 slice: a generic Adapter contract bound to a
CF1 semantic profile and implementation revision, plus validation-case and
evidence contracts that distinguish author self-tests from independent oracle
evidence. Add an Agent-side proposal binding only if it remains proposal/risk
control-plane data. Do not generate, import, execute, or install adapter code;
do not access user data, add Agent tools/routes, modify AgentCore, change the
custom runtime ABI, or claim statistical validation, model.custom execution,
Notebook integration, or capability admission.

The slice must remain generic across algorithms and consumers: every declared
operation and consumer slot is explicit, schema and profile digests are bound,
validation evidence is append-only and bounded, and E2+ evidence requires an
independent oracle reference rather than author-provided expected output.

## Boundary
- Affected paths: `backend/workbench/capability_factory/adapter_contract.py`, `backend/workbench/capability_factory/validation_contract.py`, `backend/workbench/agent/adapter_control.py`, `tests/test_capability_adapter_contract.py`, `tests/test_capability_validation_contract.py`, `tests/test_capability_adapter_control.py`
- Allowed paths: `backend/workbench/capability_factory/adapter_contract.py`, `backend/workbench/capability_factory/validation_contract.py`, `backend/workbench/agent/adapter_control.py`, `tests/test_capability_adapter_contract.py`, `tests/test_capability_validation_contract.py`, `tests/test_capability_adapter_control.py`
- Protected paths: `backend/workbench/agent/core.py`, `backend/workbench/agent/tools.py`, `backend/workbench/agent/operations.py`, `backend/workbench/agent/orchestrator.py`, `backend/workbench/http`, `backend/workbench/custom_capability`, `frontend`
- Dependencies: `v1-8-3-cf2-dependency-bundles`
- Tests: `LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/pytest -q tests/test_capability_adapter_contract.py tests/test_capability_validation_contract.py tests/test_capability_adapter_control.py`, `git diff --check`, `LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/python -m compileall -q backend/workbench/capability_factory backend/workbench/agent`
- Known gates: `no code execution, dynamic import, package install, network access, or user-data access in CF3`, `E2 and E3 evidence require an independent oracle reference; author-provided expected outputs are not authority`, `consumer support is explicit and never inherited from a built-in model`, `managed Darwin sandbox host may report typed unsupported; this is not native containment acceptance`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
No matching completed retrospective was selected.
