# Frozen Context Pack

Line: `v1-8-9-p1-capability-bootstrap-order`
Baseline SHA: `4f3ae29943feebb235ca9893186e20ae3984a2eb`

## Objective
# v1.8.9 P1 — capability registry bootstrap order

Make the live capability/workflow contract projection deterministic at import time. `imputation.mice` is registered by the runtime `ImputationStage`, so the first capability projection can omit it before the stage module is imported; later calls see it and disagree with the initial contract.

The fix must keep registry ownership modular and avoid importing optional execution packs merely to publish metadata. The same live declaration must drive the capability inventory, workflow-step vocabulary, and runtime adapter.

Acceptance: a clean-process import exposes `imputation.mice` as a composable reachable workflow capability, the denominator and reachability guard remain derived, the existing capability suites pass, and optional pack bootstrap behavior is unchanged. Browser, Provider, host resolver, and release gates remain explicit known gates.

## Boundary
- Affected paths: `backend/workbench/engine/capabilities.py`, `backend/workbench/engine/imputation_registry.py`, `backend/workbench/engine/stages/imputation.py`, `tests/test_v189_capability_bootstrap.py`, `tests/test_capability_inventory.py`
- Allowed paths: `backend/workbench/engine/capabilities.py`, `backend/workbench/engine/imputation_registry.py`, `backend/workbench/engine/stages/imputation.py`, `tests/test_v189_capability_bootstrap.py`, `tests/test_capability_inventory.py`
- Protected paths: none
- Dependencies: none
- Tests: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend:tests .venv/bin/pytest -p no:cacheprovider -q tests/test_v189_capability_bootstrap.py tests/test_capability_inventory.py`
- Known gates: `browser acceptance NOT VERIFIED`, `real Provider NOT VERIFIED`, `production host resolver NOT VERIFIED`, `release merge/tag NOT AUTHORIZED`

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

### v1-8-8-agent-chain-hardening (2026-08-10T01:59:47.000Z)

Completed formal devline v1-8-8-agent-chain-hardening; final_state=COMPLETED; failure_lesson_keys=host-gate-calendar-and-projection, host-gate-integration-before-claim, manual-browser-coverage-gap, qa-runner-is-not-cryptographic-witness, report-upstream-retry-visible, typed-failure-fail-closed

### v1-8-4-agent-evidence-loop (2026-07-28T15:52:01.000Z)

Completed formal devline v1-8-4-agent-evidence-loop; final_state=COMPLETED; failure_lesson_keys=agent-completed-operation-evidence-boundary, public-artifact-aggregate-budget

### v1-8-3-integration-acceptance (2026-07-28T12:11:00.000Z)

Completed formal devline v1-8-3-integration-acceptance; final_state=COMPLETED; failure_lesson_keys=formal-cli-command-surface, formal-scope-narrowing, supported-host-containment-required

### v1-8-3-mem3-memory-curator-exact-baseline (2026-07-27T11:35:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator-exact-baseline; final_state=COMPLETED; failure_lesson_keys=curator-contract-first, review-api-awaits-response

### v1-8-3-mem3-memory-curator (2026-07-27T11:10:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator; final_state=CLOSED; failure_lesson_keys=none

### p4-data-management (2026-08-08T23:58:00.000Z)

Completed formal devline p4-data-management; final_state=COMPLETED; failure_lesson_keys=branch-local-schema-projection, execute-provider-handler-after-projection, formal-event-vocabulary, formal-start-normalized-tags, mutation-derived-values, mutation-live-projection, mutation-no-silent-dataset-omission, p4-contract-first, preserve-existing-branch-return, review-live-registry-api, strip-composition-fields-at-adapter, typed-adapter-parameter-boundary, typed-preview-field-fidelity
