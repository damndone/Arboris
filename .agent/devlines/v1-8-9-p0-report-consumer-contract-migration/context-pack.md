# Frozen Context Pack

Line: `v1-8-9-p0-report-consumer-contract-migration`
Baseline SHA: `3257663c4236d8184805f658852f4e5a77c73f48`

## Objective
# Workbench v1.8.9 P0 Report Consumer Contract Migration

## Objective

Migrate historical tests that consume an unbound `reports/report.html` to the
current typed Report evidence contract. An unbound run must remain typed
UNAVAILABLE/failed, with no citable facts and no raw HTML authority. Preserve
owner-admitted Report tests separately; do not weaken the owner/evidence gate
or restore implicit HTML generation.

## Scope

- `tests/test_imputation_cache.py`
- `tests/test_imputation_mice.py`
- `tests/test_labels_v186.py`
- `tests/test_legacy_run_compat.py`

## Acceptance

- Focused tests pass against the typed Report projection.
- Imputation, labels, artifact counts, and model facts remain asserted through
  their durable typed artifacts or typed diagnostics.
- Legacy HTTP report routes fail closed with the typed unavailable reason when
  the host owner capability is absent; no raw HTML is reintroduced.
- Compile, diff check, formal verify, and retrospective pass.

## Non-goals

Do not change production Report authority, owner resolution, evidence transport,
or HTML rendering solely to satisfy these historical callers.

## Boundary
- Affected paths: `tests/test_imputation_cache.py`, `tests/test_imputation_mice.py`, `tests/test_labels_v186.py`, `tests/test_legacy_run_compat.py`
- Allowed paths: `tests/test_imputation_cache.py`, `tests/test_imputation_mice.py`, `tests/test_labels_v186.py`, `tests/test_legacy_run_compat.py`
- Protected paths: none
- Dependencies: none
- Tests: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend:tests .venv/bin/pytest -q tests/test_imputation_cache.py tests/test_imputation_mice.py tests/test_labels_v186.py tests/test_legacy_run_compat.py`
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
