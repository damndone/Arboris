# Frozen Context Pack

Line: `v1-8-9-p1-survey-correctness-closure`
Baseline SHA: `afc7649c81eb54ee8adcb89edc6be14fc8378d6f`

## Objective
# Workbench v1.8.9 P1 survey correctness and evidence closure

Close the audited complex-survey correctness gaps while preserving the existing
design-based estimator architecture and server-owned evidence boundary.

Required outcomes:

- generated bootstrap replicate weights are finite and non-negative, and every
  replicate matrix is validated before estimation;
- custom BRR matrices are admitted only when their encoded half-samples are
  balanced and orthogonal, while the existing published 0/1 fixture remains
  supported;
- missing or blank strata/PSU identifiers fail closed at design construction;
- survey design projections require explicit supported variance method and
  variance source, so incomplete or naive metadata cannot be presented as
  design-based evidence;
- the executable survey artifact records the variance source and central
  Agent/Notebook/Report projections accept all currently wired supported
  families, including Probit and Poisson;
- design effects remain finite for normalized weights whose total is not larger
  than the observation count, using an explicit with-replacement reference
  rather than an invalid negative finite-population correction;
- focused tests prove the red failures and green fixes, and browser/provider/
  host/release acceptance remain separate NOT VERIFIED gates.

This line does not add unimplemented survey model families, infer a design from
raw data, or turn naive standard errors into survey evidence.

## Boundary
- Affected paths: `backend/workbench/survey/replicates.py`, `backend/workbench/survey/design.py`, `backend/workbench/survey/projection.py`, `backend/workbench/engine/stages/estimation.py`, `backend/workbench/evidence/survey_projection_adapter.py`, `backend/workbench/report_view_model.py`, `tests/test_v189_survey_p1_correctness_closure.py`, `tests/test_v189_survey_central_consumer.py`
- Allowed paths: `backend/workbench/survey/replicates.py`, `backend/workbench/survey/design.py`, `backend/workbench/survey/projection.py`, `backend/workbench/engine/stages/estimation.py`, `backend/workbench/evidence/survey_projection_adapter.py`, `backend/workbench/report_view_model.py`, `tests/test_v189_survey_p1_correctness_closure.py`, `tests/test_v189_survey_central_consumer.py`
- Protected paths: none
- Dependencies: `v1-8-9-hardening-integration`
- Tests: `PYTHONPATH=backend .venv/bin/python -m pytest -q tests/test_v189_survey_p1_correctness_closure.py tests/test_v189_survey_central_consumer.py`, `git diff --check`
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

### v1-8-5-a5-model-packet-lineage-label (2026-08-01T22:24:00.000Z)

Completed formal devline v1-8-5-a5-model-packet-lineage-label; final_state=COMPLETED; failure_lesson_keys=model-packet-downstream-boundary

### wo-a-agent (2026-07-20T17:44:54.000Z)

Completed formal devline wo-a-agent; final_state=CLOSED; failure_lesson_keys=filesystem-persistence-capability-bypass
