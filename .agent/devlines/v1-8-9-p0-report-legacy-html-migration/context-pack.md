# Frozen Context Pack

Line: `v1-8-9-p0-report-legacy-html-migration`
Baseline SHA: `968328119632b9fa52e0f263724f7a7733d44ced`

## Objective
# Workbench v1.8.9 P0 Report Legacy Contract Migration

Migrate remaining legacy tests that treat an unbound local HTML file as an authoritative Report result. Preserve the v1.8.9 fail-closed rule: an unbound run may expose typed diagnostics and unavailable evidence, but must not expose citable Report facts or raw fallback HTML.

Scope: tests/models/arma_garch/test_deliverables.py, tests/test_cs_did_wiring.py, tests/test_debug_audit.py.

Acceptance: focused tests pass; assertions use typed evidence/diagnostic contracts; server-owner-admitted Report tests remain authoritative; no production Report weakening.

## Boundary
- Affected paths: `tests/models/arma_garch/test_deliverables.py`, `tests/test_cs_did_wiring.py`, `tests/test_debug_audit.py`
- Allowed paths: `tests/models/arma_garch/test_deliverables.py`, `tests/test_cs_did_wiring.py`, `tests/test_debug_audit.py`
- Protected paths: none
- Dependencies: none
- Tests: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend:tests .venv/bin/pytest -q tests/models/arma_garch/test_deliverables.py tests/test_cs_did_wiring.py tests/test_debug_audit.py`
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

### v1-8-5-c1-regression-family-admission (2026-08-01T13:48:08.000Z)

Completed formal devline v1-8-5-c1-regression-family-admission; final_state=COMPLETED; failure_lesson_keys=family-column-fields-preserve-elementwise, family-contract-drives-source-schema-validation, family-input-validation-before-genesis, materialization-uses-family-contract-not-ols-heuristic, model-family-field-ownership-fail-closed, normalized-fms-tag-before-start, notebook-delegates-to-shared-family-contract, regression-family-contract-before-admission
