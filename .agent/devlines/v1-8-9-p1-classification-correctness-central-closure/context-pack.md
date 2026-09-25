# Frozen Context Pack

Line: `v1-8-9-p1-classification-correctness-central-closure`
Baseline SHA: `afc7649c81eb54ee8adcb89edc6be14fc8378d6f`

## Objective
# Workbench v1.8.9 P1 — classification correctness and central consumer closure

## Objective

Close the remaining P1 classification-ML gaps in the candidate worktree. The
production protocol must select models from the declared development OOF
probabilities under the selected decision threshold, calculate probability
metrics from probabilities, keep calibration and threshold scopes truthful,
and produce bounded explanations when the model family supports them. Agent,
Notebook, and Report must consume the same server-owned typed classification
projection for a persisted run; no consumer may reconstruct classification
results from generic raw-result readers.

## Acceptance criteria

1. Model comparison uses the declared thresholded OOF predictions for metrics
   whose definition is thresholded, and probability metrics use probabilities.
2. `threshold_curve` calculates log loss from probability columns, not hard
   class labels; threshold records name the actual input scope.
3. Supported classification models emit bounded, typed explanation evidence or
   a truthful unavailable/degraded reason with stable provenance.
4. Agent, Notebook, and Report central readers return the same persisted
   classification projection, including status, source identity, comparison,
   threshold, calibration, and explanations.
5. Holdout remains sealed until the existing explicit release boundary, and all
   invalid, malformed, or unbound packets fail closed.

## In scope

- `backend/workbench/predictive_research/classification_protocol.py`
- `backend/workbench/predictive_research/classification_metrics.py`
- `backend/workbench/predictive_research/classification_explanations.py`
- `backend/workbench/prediction.py`
- `backend/workbench/services/classification_consumer_service.py`
- `backend/workbench/agent/context_tools.py`
- `backend/workbench/agent/notebook/evidence.py`
- `tests/test_v189_classification_p1_correctness_central_closure.py`
- relevant existing classification protocol, production, and central-consumer tests

## Out of scope / known gates

Browser acceptance, real provider execution, host-only full-gate containment,
release packaging, and external benchmark parity are separate gates and must
not be represented as passed by this line.

## Safety and extensibility constraints

Keep the protocol family-agnostic and typed: use adapter capabilities and
projection contracts rather than model-name branches where possible. Preserve
server-owned identity and evidence provenance. Do not expose raw serialized
model state, arbitrary file paths, or unbounded explanation payloads to Agent,
Notebook, or Report.

## Boundary
- Affected paths: `backend/workbench/predictive_research/classification_protocol.py`, `backend/workbench/predictive_research/classification_metrics.py`, `backend/workbench/predictive_research/classification_explanations.py`, `backend/workbench/prediction.py`, `backend/workbench/services/classification_consumer_service.py`, `backend/workbench/agent/context_tools.py`, `backend/workbench/agent/notebook/evidence.py`, `tests/test_v189_classification_p1_correctness_central_closure.py`, `tests/test_v189_classification_production.py`, `tests/test_v189_classification_central_consumer.py`
- Allowed paths: `backend/workbench/predictive_research/classification_protocol.py`, `backend/workbench/predictive_research/classification_metrics.py`, `backend/workbench/predictive_research/classification_explanations.py`, `backend/workbench/prediction.py`, `backend/workbench/services/classification_consumer_service.py`, `backend/workbench/agent/context_tools.py`, `backend/workbench/agent/notebook/evidence.py`, `tests/test_v189_classification_p1_correctness_central_closure.py`, `tests/test_v189_classification_production.py`, `tests/test_v189_classification_central_consumer.py`
- Protected paths: none
- Dependencies: none
- Tests: `PYTHONPATH=backend .venv/bin/python -m pytest -q tests/test_v189_classification_p1_correctness_central_closure.py`, `PYTHONPATH=backend .venv/bin/python -m pytest -q tests/test_v189_classification_production.py tests/test_v189_classification_central_consumer.py`
- Known gates: `browser`, `provider`, `host_full_gate`, `release`

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

### v1-8-8-p7-agent-adoption (2026-08-09T03:20:32.000Z)

Completed formal devline v1-8-8-p7-agent-adoption; final_state=COMPLETED; failure_lesson_keys=browser-report-remains-not-verified, declaration-derived-option-boundaries, design-diagnostic-neutral-envelope, generated-tool-schema-runtime-validation, p7-artifact-identity-preserves-repeatability, parent-workflow-owns-child-vocabulary, workflow-errors-preserve-step-cause

### p4-data-management (2026-08-08T23:58:00.000Z)

Completed formal devline p4-data-management; final_state=COMPLETED; failure_lesson_keys=branch-local-schema-projection, execute-provider-handler-after-projection, formal-event-vocabulary, formal-start-normalized-tags, mutation-derived-values, mutation-live-projection, mutation-no-silent-dataset-omission, p4-contract-first, preserve-existing-branch-return, review-live-registry-api, strip-composition-fields-at-adapter, typed-adapter-parameter-boundary, typed-preview-field-fidelity

### v1-8-5-c4-projection-registry (2026-08-01T21:58:07.000Z)

Completed formal devline v1-8-5-c4-projection-registry; final_state=COMPLETED; failure_lesson_keys=projection-registry-before-recipe-growth

### v1-8-5-c3-recipe-preflight-projection (2026-08-01T21:47:00.000Z)

Completed formal devline v1-8-5-c3-recipe-preflight-projection; final_state=COMPLETED; failure_lesson_keys=c3-gate-dedicated-basetemp, recipe-preflight-before-draft

### v1-8-4-reopened-incident-truth (2026-07-31T08:10:00.000Z)

Completed formal devline v1-8-4-reopened-incident-truth; final_state=COMPLETED; failure_lesson_keys=full-gate-requires-non-nested-seatbelt, gate-requires-non-nested-sandbox
