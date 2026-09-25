# Frozen Context Pack

Line: `v1-8-9-p0-artifact-registry-vocabulary`
Baseline SHA: `afc7649c81eb54ee8adcb89edc6be14fc8378d6f`

## Objective
# Workbench v1.8.9 P0 Artifact Registry Vocabulary

## Objective

Make the canonical run artifact registry recognize the already-produced typed
`measurement_advisory` artifact, including its indexed file/digest and report
consumer boundary. Keep the registry closed: accept only explicitly declared
producer artifact types, reject forged or unknown types, and preserve
fail-closed behavior for invalid records.

## Scope

- `backend/workbench/repository/run_repository.py`
- `backend/workbench/engine/stages/ytype.py`
- `tests/test_v189_artifact_contracts.py`
- `tests/test_statistics_api_e2e_v186.py`

## Acceptance

- A valid `measurement_advisory` artifact can be listed and consumed through
  the canonical indexed path with digest verification.
- Unknown and forged artifact types remain rejected.
- The statistical Report/Agent surface either consumes the typed packet through
  the validated index or returns typed unavailable; no raw-file fallback is
  restored.
- Existing artifact registry and statistics focused tests pass.

## Boundary

- Affected paths: the four paths above
- Allowed paths: the four paths above
- Protected paths: evidence authority, Agent/Notebook compiler, unrelated model estimators, release state
- Dependencies: current canonical artifact index contract
- Tests: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend:tests .venv/bin/pytest -q tests/test_v189_artifact_contracts.py tests/test_statistics_api_e2e_v186.py`
- Known gates: full backend, browser, production host/provider, and release gates remain separate

## Boundary
- Affected paths: `backend/workbench/repository/run_repository.py`, `backend/workbench/engine/stages/ytype.py`, `tests/test_v189_artifact_contracts.py`, `tests/test_statistics_api_e2e_v186.py`
- Allowed paths: `backend/workbench/repository/run_repository.py`, `backend/workbench/engine/stages/ytype.py`, `tests/test_v189_artifact_contracts.py`, `tests/test_statistics_api_e2e_v186.py`
- Protected paths: `backend/workbench/evidence`, `backend/workbench/agent`, `backend/workbench/predictive_research`
- Dependencies: `current canonical artifact index contract`
- Tests: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend:tests .venv/bin/pytest -q tests/test_v189_artifact_contracts.py tests/test_statistics_api_e2e_v186.py`
- Known gates: `full backend, browser, production host/provider, and release acceptance remain separate`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_markdown":"# Global Development Rules\n\nGenerated from repeated devline events. Mandatory rules have appeared at least three times.\n\n- `REVIEW|persistence_capability_bypass|filesystem persistence capability bypass` — A sealed input is insufficient when packet and index writes retain a raw-path escape. (resolution: define admission-gated FD-only writer)\n","global_rules_markdown_sha256":"b619424541a214099df16821c0642f4b2ddb9ee498f66cce7dece275b1117fe5","global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"7d2646296aff49c2c92e83e53f6ad44990aec4280746ec5cf7d9f40b3ab87598"}
```

## Mandatory global development rules
# Global Development Rules

Generated from repeated devline events. Mandatory rules have appeared at least three times.

- `REVIEW|persistence_capability_bypass|filesystem persistence capability bypass` — A sealed input is insufficient when packet and index writes retain a raw-path escape. (resolution: define admission-gated FD-only writer)

## Selected historical lessons
### v1-8-8-statistical-truth-cleanup (2026-08-13T10:11:25.000Z)

Completed formal devline v1-8-8-statistical-truth-cleanup; final_state=COMPLETED; failure_lesson_keys=none

### v1-8-4-agent-evidence-loop (2026-07-28T15:52:01.000Z)

Completed formal devline v1-8-4-agent-evidence-loop; final_state=COMPLETED; failure_lesson_keys=agent-completed-operation-evidence-boundary, public-artifact-aggregate-budget

### v1-8-3-integration-acceptance (2026-07-28T12:11:00.000Z)

Completed formal devline v1-8-3-integration-acceptance; final_state=COMPLETED; failure_lesson_keys=formal-cli-command-surface, formal-scope-narrowing, supported-host-containment-required

### v1-8-3-mem3-memory-curator-exact-baseline (2026-07-27T11:35:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator-exact-baseline; final_state=COMPLETED; failure_lesson_keys=curator-contract-first, review-api-awaits-response

### v1-8-3-mem3-memory-curator (2026-07-27T11:10:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator; final_state=CLOSED; failure_lesson_keys=none
