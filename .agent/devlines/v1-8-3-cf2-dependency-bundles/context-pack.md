# Frozen Context Pack

Line: `v1-8-3-cf2-dependency-bundles`
Baseline SHA: `04faee1bab8b5a4d177af1e8c46f66e527b3b9bf`

## Objective
# v1.8.3 CF2 deterministic dependency bundles

Implement the dependency control-plane foundation for Capability Factory:
immutable dependency requirements and lock records, networked fetch metadata
separated from offline quarantine/assembly, safe wheel/archive inspection,
content-addressed bundle candidates, and explicit admission states. Route only
dependency acquisition proposals through the existing high-risk Agent policy;
do not install packages in the Workbench environment, import or execute fetched
code, access user data, mount application routes, or modify AgentCore/model/tool
surfaces. Keep bundle validity separate from evidence and scoped admission.

This slice may implement unmounted service contracts and deterministic tests only;
it does not claim third-party capability validation, custom execution, native
containment acceptance, or Notebook integration.

## Boundary
- Affected paths: `backend/workbench/capability_factory`, `backend/workbench/agent/dependency_control.py`, `backend/workbench/agent/operations.py`, `backend/workbench/agent/orchestrator.py`, `backend/workbench/agent/risk.py`, `backend/workbench/http/agent_routes.py`, `backend/workbench/http/capability_routes.py`, `tests/fixtures/capability_factory/wheels`, `tests/test_capability_dependency_contract.py`, `tests/test_capability_dependency_resolver.py`, `tests/test_capability_dependency_fetch.py`, `tests/test_capability_wheel_inspection.py`, `tests/test_capability_bundle_assembler.py`, `tests/test_capability_bundle_admission.py`, `tests/test_capability_dependency_service.py`, `tests/test_capability_dependency_risk.py`, `tests/test_capability_dependency_trace.py`
- Allowed paths: `backend/workbench/capability_factory/dependency_contract.py`, `backend/workbench/capability_factory/dependency_resolver.py`, `backend/workbench/capability_factory/dependency_store.py`, `backend/workbench/capability_factory/dependency_fetch.py`, `backend/workbench/capability_factory/wheel_inspection.py`, `backend/workbench/capability_factory/bundle_assembler.py`, `backend/workbench/capability_factory/bundle_admission.py`, `backend/workbench/capability_factory/dependency_service.py`, `backend/workbench/capability_factory/trace_contracts.py`, `backend/workbench/agent/dependency_control.py`, `backend/workbench/agent/operations.py`, `backend/workbench/agent/orchestrator.py`, `backend/workbench/agent/risk.py`, `backend/workbench/http/agent_routes.py`, `backend/workbench/http/capability_routes.py`, `tests/fixtures/capability_factory/wheels`, `tests/test_capability_dependency_contract.py`, `tests/test_capability_dependency_resolver.py`, `tests/test_capability_dependency_fetch.py`, `tests/test_capability_wheel_inspection.py`, `tests/test_capability_bundle_assembler.py`, `tests/test_capability_bundle_admission.py`, `tests/test_capability_dependency_service.py`, `tests/test_capability_dependency_risk.py`, `tests/test_capability_dependency_trace.py`
- Protected paths: none
- Dependencies: `v1-8-3-cf1-capability-resolution`, `v1-8-3-b1-native-containment`
- Tests: `LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/pytest -q tests/test_capability_dependency_contract.py tests/test_capability_dependency_resolver.py tests/test_capability_dependency_fetch.py tests/test_capability_wheel_inspection.py tests/test_capability_bundle_assembler.py tests/test_capability_bundle_admission.py tests/test_capability_dependency_service.py tests/test_capability_dependency_risk.py tests/test_capability_dependency_trace.py tests/test_risk_policy.py tests/test_agent_generic_workflow.py tests/test_no_exercise_specific_naming.py`, `git diff --check`, `LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 .venv/bin/python scripts/devline_control.py verify --line v1-8-3-cf2-dependency-bundles`
- Known gates: `Networked metadata and artifact fetch is isolated from offline quarantine assembly, offline validation, and analysis runtime.`, `Fetched artifacts are never imported or executed; the main Workbench environment is never dynamically installed into.`, `Reject mutable references, hash mismatch, redirects outside policy, unsafe archive members, symlinks, path traversal, hooks, and hostile metadata.`, `Dependency acquisition remains a high-risk proposal/confirmation/audit path; no AgentCore or arbitrary code.execute surface is opened by this line.`, `CF2 does not claim statistical evidence, native containment acceptance, model.custom execution, or Notebook readiness.`, `Do not push, open a PR, merge, tag, or release without explicit user authorization.`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
No matching completed retrospective was selected.
