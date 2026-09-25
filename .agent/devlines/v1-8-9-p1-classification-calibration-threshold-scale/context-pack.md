# Frozen Context Pack

Line: `v1-8-9-p1-classification-calibration-threshold-scale`
Baseline SHA: `afc7649c81eb54ee8adcb89edc6be14fc8378d6f`

## Objective
# Objective: v1.8.9 P1 classification calibration/threshold scale

## Objective

Make classification threshold evidence truthful when probability calibration is
enabled. The development OOF threshold used for model comparison and search
must remain distinct from the operational threshold consumed against calibrated
holdout probabilities. No released prediction may compare calibrated
probabilities with a raw-probability threshold.

## Acceptance criteria

- `selection_threshold` is explicitly bound to the full development OOF raw
  probability scope and remains the score used for model comparison/search.
- `threshold` is explicitly bound to the disjoint development calibration
  evaluation scope and the probability scale consumed at final holdout.
- The selected operational threshold and its precision constraint are computed
  on the same calibrated probability scale as final holdout predictions.
- Threshold row identities, scopes, source labels, release-plan hashes, and
  Agent/Notebook/Report projections remain typed and provenance-bound.
- Holdout remains sealed until the existing C0 release boundary; malformed or
  unavailable calibration/threshold evidence fails closed.

## Boundaries

In scope: production classification threshold/calibration evidence and its
tests. Out of scope: new model families, provider startup, browser acceptance,
and release/tag operations.

## Known gates

Browser acceptance, real provider acceptance, host/full gate, merge/tag, and
release readiness are not verified by this objective.

## Boundary
- Affected paths: `backend/workbench/predictive_research/classification_protocol.py`, `tests/test_v189_classification_p1_correctness_central_closure.py`, `tests/test_v189_classification_production.py`
- Allowed paths: `backend/workbench/predictive_research/classification_protocol.py`, `tests/test_v189_classification_p1_correctness_central_closure.py`, `tests/test_v189_classification_production.py`
- Protected paths: none
- Dependencies: none
- Tests: `PYTHONPATH=backend .venv/bin/python -m pytest -q tests/test_v189_classification_p1_correctness_central_closure.py tests/test_v189_classification_production.py`
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
