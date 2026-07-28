# Frozen Context Pack

Line: `v1-8-3-cf3b-bundle-admission`
Baseline SHA: `24d98051ac6bdb33eb5008aec1a26f1a4a3b920f`

## Objective
# CF3B exact registration and scoped admission

Implement the narrow CF3B control-plane boundary from the approved v1.8.3
Capability Factory design. Register only an exact already-validated
ImplementationRevision together with its AdapterContract, ValidationBundle,
server EvidenceAssessment, runtime policy ref, and host-containment ref.
Make the registration immutable and idempotent for the same identity, reject
rebinding or successor substitution, and expose a scoped-admission service that
delegates to the existing server-owned admission controller. This phase must
remain execution-free, network-free, and unmounted from Agent/HTTP/Notebook.

## Boundary
- Affected paths: `backend/workbench/capability_factory/registry.py`, `backend/workbench/capability_factory/admission_service.py`, `backend/workbench/capability_factory/trace_contracts.py`, `backend/workbench/native_containment/host.py`, `tests/test_capability_implementation_registration.py`, `tests/test_capability_admission_service.py`, `tests/test_capability_factory_trace.py`, `tests/test_native_containment_host.py`
- Allowed paths: `backend/workbench/capability_factory/registry.py`, `backend/workbench/capability_factory/admission_service.py`, `backend/workbench/capability_factory/trace_contracts.py`, `backend/workbench/native_containment/host.py`, `tests/test_capability_implementation_registration.py`, `tests/test_capability_admission_service.py`, `tests/test_capability_factory_trace.py`, `tests/test_native_containment_host.py`
- Protected paths: `backend/workbench/agent`, `backend/workbench/http`, `backend/workbench/custom_capability`, `frontend`, `scripts`, `tests/test_sandbox.py`, `tests/test_code_execution.py`
- Dependencies: `v1-8-3-cf3-validation-runtime`, `v1-8-3-b1-native-containment`
- Tests: `LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/pytest -q tests/test_capability_implementation_registration.py tests/test_capability_admission_service.py tests/test_capability_factory_trace.py tests/test_no_exercise_specific_naming.py`, `git diff --check`
- Known gates: `B1 host containment remains unsupported on this managed macOS host; CF3B must not make a binding executable without native assessment`, `CF3 evidence and admission are separate server-owned facts; no caller-controlled tier or source_eligible`, `no Agent, HTTP, Notebook, network, import, or execution surface in this line`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
No matching completed retrospective was selected.
