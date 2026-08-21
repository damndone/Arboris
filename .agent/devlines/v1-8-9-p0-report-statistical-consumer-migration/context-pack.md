# Frozen Context Pack

Line: `v1-8-9-p0-report-statistical-consumer-migration`
Baseline SHA: `cfd8cc3294f2842ef89cfad207f2831fca13964c`

## Objective
# Workbench v1.8.9 P0 Statistical Consumer Migration

## Objective

Migrate remaining statistical tests that consume `reports/report.html` or
assume legacy Report output to the typed diagnostic, model-result, label, and
Report-unavailable contracts. Preserve the actual statistical assertions and
ensure unsupported/unbound presentation remains fail-closed.

## Scope

- `tests/test_ols_weights_v186.py`
- `tests/test_orchestrator_e2e.py`
- `tests/test_p0_regression.py`

## Acceptance

- Focused tests pass without restoring unbound HTML authority.
- Weighting, Poisson offset/fallback, model outputs, diagnostics, and lineage
  remain asserted through durable typed evidence.
- Any Report assertion uses typed unavailable evidence when the host owner is
  absent.
- Compile, diff check, formal verify, and retrospective pass.

## Non-goals

Do not modify statistical estimators or weaken model result correctness merely
to satisfy presentation-only assertions.

## Boundary
- Affected paths: `tests/test_ols_weights_v186.py`, `tests/test_orchestrator_e2e.py`, `tests/test_p0_regression.py`
- Allowed paths: `tests/test_ols_weights_v186.py`, `tests/test_orchestrator_e2e.py`, `tests/test_p0_regression.py`
- Protected paths: none
- Dependencies: none
- Tests: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend:tests .venv/bin/pytest -q tests/test_ols_weights_v186.py tests/test_orchestrator_e2e.py tests/test_p0_regression.py`
- Known gates: none

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
