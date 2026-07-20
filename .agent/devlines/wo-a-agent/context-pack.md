# Frozen Context Pack

Line: `wo-a-agent`
Baseline SHA: `0251f0a30d984bdbb2cfab404e6c646deab60cae`

## Objective
Preserve the reviewed LMM Agent persistence boundary while integration resolves its single trusted admission capability.

## Boundary
- Affected paths: `backend/workbench/services/pinned_run_directory.py`, `backend/workbench/engine/packs/linear_mixed_effects`, `backend/workbench/services/run_service.py`, `backend/workbench/engine/stages/estimation.py`, `backend/workbench/engine/context.py`, `backend/workbench/orchestrator/__init__.py`, `tests/test_pinned_run_directory.py`, `tests/models/linear_mixed_effects/test_pinned_persistence.py`, `tests/models/linear_mixed_effects/test_runner.py`, `tests/engine/test_lmm_execution_admission.py`, `tests/contracts/test_lmm_error_contract.py`, `tests/test_lmm_result_adapter.py`, `tests/test_lmm_extension_seams.py`
- Allowed paths: `backend/workbench/services/pinned_run_directory.py`, `backend/workbench/engine/packs/linear_mixed_effects`, `backend/workbench/services/run_service.py`, `backend/workbench/engine/stages/estimation.py`, `backend/workbench/engine/context.py`, `backend/workbench/orchestrator/__init__.py`, `tests/test_pinned_run_directory.py`, `tests/models/linear_mixed_effects/test_pinned_persistence.py`, `tests/models/linear_mixed_effects/test_runner.py`, `tests/engine/test_lmm_execution_admission.py`, `tests/contracts/test_lmm_error_contract.py`, `tests/test_lmm_result_adapter.py`, `tests/test_lmm_extension_seams.py`
- Protected paths: `scripts/gate.sh`
- Dependencies: none
- Tests: `tests/test_pinned_run_directory.py`
- Known gates: `focused-pytest`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
No matching completed retrospective was selected.
