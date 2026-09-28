# Frozen Context Pack

Line: `v1-8-9-p0-report-legacy-contract-migration`
Baseline SHA: `d0b2b2337dd7debdd1a0a976e563a2045ec469f9`

## Objective
# Workbench v1.8.9 P0 Report Legacy Contract Migration Objective

Migrate only stale legacy expectations in the report-adjacent regression tests
to the current fail-closed Report contract. An unbound local run must not be
treated as producing `report.html`; preserve assertions for model outputs,
diagnostics, categorical interpretation, and typed unavailable evidence.

Do not change production evidence authority, add a test-only owner, or remove
dedicated owner-admitted Report positive tests elsewhere.

## Scope

- `tests/test_api.py`
- `tests/test_auto_infer_batch.py`
- `tests/test_categorical_and_batch.py`

## Verification gates

- Scoped pytest suite for the three owned files, with the exact pass count
  recorded in the handoff.
- `PYTHONPATH=backend .venv/bin/python -m compileall -q backend tests`
- `git diff --check`
- Formal event-log verification and retrospective generation through
  `scripts/devline_control.py`.

## Boundary
- Affected paths: `tests/test_api.py`, `tests/test_auto_infer_batch.py`, `tests/test_categorical_and_batch.py`
- Allowed paths: `tests/test_api.py`, `tests/test_auto_infer_batch.py`, `tests/test_categorical_and_batch.py`
- Protected paths: `backend/workbench/reporting.py`, `backend/workbench/report_quality.py`, `backend/workbench/evidence`
- Dependencies: `v1-8-9-foundation-integration`
- Tests: `PYTHONPATH=backend .venv/bin/python -m pytest tests/test_api.py tests/test_auto_infer_batch.py tests/test_categorical_and_batch.py -q`, `PYTHONPATH=backend .venv/bin/python -m compileall -q backend tests`, `git diff --check`
- Known gates: `unbound local runs remain fail-closed for Report`, `model outputs, diagnostics, categorical interpretation, and typed unavailable evidence remain asserted`, `dedicated owner-admitted Report positive tests remain outside this line and unchanged`, `formal verify and retrospective are required before close`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

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
