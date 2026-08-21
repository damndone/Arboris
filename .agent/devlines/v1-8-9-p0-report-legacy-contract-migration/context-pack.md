# Frozen Context Pack

Line: `v1-8-9-p0-report-legacy-contract-migration`
Baseline SHA: `4f3ae29943feebb235ca9893186e20ae3984a2eb`

## Objective
# v1.8.9 P0 — migrate legacy report tests to the fail-closed contract

Migrate broad legacy tests that assume an unbound local run automatically writes and serves `reports/report.html`. The v1.8.9 contract requires a server-owned Report evidence capability; without deployment-owned host admission, the correct result is typed unavailable/blocked evidence with model artifacts retained.

Keep dedicated owner-admitted Report tests as the positive path. Do not weaken production evidence admission, invent a test-only owner in production code, or change numerical/report claims to read raw model files.

Acceptance: the owned legacy tests assert the current typed unavailable behavior where no C0 owner is injected, while preserving non-report model/diagnostic assertions. The scoped suite, compile/diff checks, and formal verification pass. Browser, real Provider, external host resolver, and release gates remain explicit known gates.

## Boundary
- Affected paths: `tests/test_api.py`, `tests/test_auto_infer_batch.py`, `tests/test_categorical_and_batch.py`
- Allowed paths: `tests/test_api.py`, `tests/test_auto_infer_batch.py`, `tests/test_categorical_and_batch.py`
- Protected paths: none
- Dependencies: none
- Tests: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend:tests .venv/bin/pytest -p no:cacheprovider -q tests/test_api.py tests/test_auto_infer_batch.py tests/test_categorical_and_batch.py`
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

### v1-8-4-agent-evidence-loop (2026-07-28T15:52:01.000Z)

Completed formal devline v1-8-4-agent-evidence-loop; final_state=COMPLETED; failure_lesson_keys=agent-completed-operation-evidence-boundary, public-artifact-aggregate-budget

### v1-8-3-integration-acceptance (2026-07-28T12:11:00.000Z)

Completed formal devline v1-8-3-integration-acceptance; final_state=COMPLETED; failure_lesson_keys=formal-cli-command-surface, formal-scope-narrowing, supported-host-containment-required

### v1-8-3-mem3-memory-curator-exact-baseline (2026-07-27T11:35:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator-exact-baseline; final_state=COMPLETED; failure_lesson_keys=curator-contract-first, review-api-awaits-response

### v1-8-3-mem3-memory-curator (2026-07-27T11:10:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator; final_state=CLOSED; failure_lesson_keys=none
