# Frozen Context Pack

Line: `v1-8-3-cf4-admission-control`
Baseline SHA: `1b184681e30091104219ec2c2ec6e7de62cce859`

## Objective
# v1.8.3 CF4 scoped admission control-plane foundation

Implement one bounded CF4 slice: derive a server-owned EvidenceAssessment from
the CF3 validation bundle, record append-only validity changes, and bind a
scoped capability admission record to the exact adapter, validation bundle,
assessment, runtime policy, operations, and consumer slots. Add an Agent-side
high-risk proposal binding through the existing ProposalStore and
RiskAuthorizationStore only; do not consume a grant or execute an adapter.

Evidence tier and admission state must remain separate. E1 or lower evidence
must not become normally source-eligible merely because a user confirms an
admission proposal. Admission must fail closed on identity, freshness, scope,
operation, consumer, or validity mismatches. Keep the slice generic across
capability kinds and avoid modifying Notebook, Graph, HTTP, workflow, AgentCore,
registry, runtime ABI, user-data access, network access, imports, installation,
or execution surfaces.

## Boundary
- Affected paths: `backend/workbench/capability_factory/admission_contract.py`, `backend/workbench/agent/admission_control.py`, `tests/test_capability_admission_contract.py`, `tests/test_capability_admission_control.py`
- Allowed paths: `backend/workbench/capability_factory/admission_contract.py`, `backend/workbench/agent/admission_control.py`, `tests/test_capability_admission_contract.py`, `tests/test_capability_admission_control.py`
- Protected paths: `backend/workbench/capability_factory/contracts.py`, `backend/workbench/custom_capability`, `backend/workbench/agent/core.py`, `backend/workbench/agent/tools.py`, `backend/workbench/agent/operations.py`, `backend/workbench/agent/orchestrator.py`, `backend/workbench/http`, `frontend`
- Dependencies: `v1-8-3-cf3-adapter-validation`
- Tests: `LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/pytest -q tests/test_capability_admission_contract.py tests/test_capability_admission_control.py`, `git diff --check`, `LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/python -m compileall -q backend/workbench/capability_factory backend/workbench/agent`
- Known gates: `no code execution, dynamic import, package install, network access, or user-data access in CF4`, `evidence tier and admission state remain independent; confirmation cannot raise E1 to E2`, `freshness and scope mismatches fail closed`, `managed Darwin sandbox host may report typed unsupported; this is not native containment acceptance`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
No matching completed retrospective was selected.
