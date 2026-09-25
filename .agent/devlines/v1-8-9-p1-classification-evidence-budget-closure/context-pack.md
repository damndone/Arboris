# Frozen Context Pack

Line: `v1-8-9-p1-classification-evidence-budget-closure`
Baseline SHA: `afc7649c81eb54ee8adcb89edc6be14fc8378d6f`

## Objective
# Workbench v1.8.9 P1 classification evidence budget closure

Close the current candidate regression where a normal, complete typed
classification packet is rejected by the server-owned provider projection
catalog because its deterministic structured-size estimate is larger than the
declared budget. Preserve the hard fail-closed budget guard, raw-field
rejection, row bound, catalog identity, and Agent/Notebook/Report shared
projection. The fix must change the explicit bounded classification contract,
not bypass admission or silently drop evidence.

Required outcomes:

- the complete normal classification packet is admitted by all three central
  consumers with a declared bounded budget;
- oversized, raw, foreign, and malformed packets remain rejected;
- the server-side ceiling and catalog declaration agree, and the projection
  exposes the observed token/row counts and identity;
- focused tests prove the red failure before the fix and green behavior after;
- browser, provider, host full-gate, and release acceptance remain separate
  NOT VERIFIED gates.

Scope: `backend/workbench/evidence/provider_projection_adapters.py`,
`backend/workbench/providers/builtin/classification_ml.json`,
`tests/test_v189_classification_central_consumer.py`, and
`tests/test_v189_classification_projection_adapter.py` only.

## Boundary
- Affected paths: `backend/workbench/evidence/provider_projection_adapters.py`, `backend/workbench/providers/builtin/classification_ml.json`, `tests/test_v189_classification_central_consumer.py`, `tests/test_v189_classification_projection_adapter.py`
- Allowed paths: `backend/workbench/evidence/provider_projection_adapters.py`, `backend/workbench/providers/builtin/classification_ml.json`, `tests/test_v189_classification_central_consumer.py`, `tests/test_v189_classification_projection_adapter.py`
- Protected paths: `backend/workbench/agent`, `backend/workbench/services`, `backend/workbench/http`, `frontend/src`, `scripts`
- Dependencies: `v1-8-9-hardening-integration`
- Tests: `PYTHONPATH=backend .venv/bin/python -m pytest -q tests/test_v189_classification_central_consumer.py tests/test_v189_classification_projection_adapter.py`, `git diff --check`
- Known gates: `browser_acceptance_NOT_VERIFIED`, `provider_acceptance_NOT_VERIFIED`, `host_full_gate_NOT_VERIFIED`, `release_NOT_VERIFIED`

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
