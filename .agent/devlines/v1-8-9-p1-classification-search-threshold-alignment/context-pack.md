# Frozen Context Pack

Line: `v1-8-9-p1-classification-search-threshold-alignment`
Baseline SHA: `afc7649c81eb54ee8adcb89edc6be14fc8378d6f`

## Objective
# Objective: v1.8.9 P1 classification search threshold alignment

## Objective

Make bounded classification model search score every candidate with the same
development-only decision rule used by the production classification protocol.
The search must not rank candidates with a hidden fixed 0.5 threshold when the
declared decision policy selects a different OOF threshold. The change must
preserve holdout sealing, typed evidence, bounded receipts, and fail-closed
behavior.

## Acceptance criteria

- A production bounded-search trial derives its threshold from that trial's
  development OOF probabilities using the declared decision policy.
- Search and final model comparison expose the same primary-metric value for
  the same candidate and immutable split.
- Threshold scope remains development-only and no holdout labels or
  probabilities enter the search evaluator.
- Generic `run_bounded_search` callers remain backward compatible: the
  evaluator still supplies a typed development OOF metric bundle.
- Regression tests cover max-F1 and precision-constrained threshold policies,
  and the existing classification/search suites remain green.

## Boundaries

In scope: the production classification search evaluator and its tests.
Out of scope: new model families, provider startup, browser acceptance, and
release/tag operations.

## Known gates

Browser acceptance, real provider acceptance, host/full gate, merge/tag, and
release readiness are not verified by this objective.

## Boundary
- Affected paths: `backend/workbench/predictive_research/classification_protocol.py`, `backend/workbench/predictive_research/classification_search.py`, `tests/predictive_research/test_classification_search_v189.py`, `tests/test_v189_classification_search_threshold_alignment.py`
- Allowed paths: `backend/workbench/predictive_research/classification_protocol.py`, `backend/workbench/predictive_research/classification_search.py`, `tests/predictive_research/test_classification_search_v189.py`, `tests/test_v189_classification_search_threshold_alignment.py`
- Protected paths: none
- Dependencies: none
- Tests: `PYTHONPATH=backend .venv/bin/python -m pytest -q tests/test_v189_classification_search_threshold_alignment.py`, `PYTHONPATH=backend .venv/bin/python -m pytest -q tests/predictive_research/test_classification_search_v189.py tests/test_v189_classification_production.py`
- Known gates: `browser_acceptance_not_verified`, `real_provider_not_verified`, `host_full_gate_not_verified`, `release_not_verified`

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
