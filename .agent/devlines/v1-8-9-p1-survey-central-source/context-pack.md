# Frozen Context Pack

Line: `v1-8-9-p1-survey-central-source`
Baseline SHA: `91ee6a05eab2a1892844c8a3057e1e607359a29e`

## Objective
# Workbench v1.8.9 P1 Survey central source objective

## Objective

Give Survey results the same server-owned source and projection foundation
already required for classification. A persisted Survey run, after exact
artifact/receipt/identity validation, must yield one opaque source snapshot
that can be projected for Agent and Notebook without accepting a path, raw
packet, caller registry, or forged capability. The provider contribution must
be catalog-visible and model-agnostic across supported Survey OLS/Logit
families. Unsupported families remain typed unavailable; this slice must not
increase estimator count or change variance semantics.

## Acceptance

- source snapshot is issued only from an authorized persisted receipt;
- Survey identity, evidence status, design metadata, and unavailable reason
  survive the adapter without recomputation;
- Agent/Notebook adapters use the same source snapshot and reject path/raw
  bypasses;
- provider declaration is deterministic and coverage-visible;
- focused adversarial tests, compileall, diff check, and formal verification
  pass.

## Non-goals

No Survey estimator changes, no Report/HTTP renderer mount, no new model
families, no `.sav/.dta`, no browser/provider/full-gate/release.

## Boundary
- Affected paths: `backend/workbench/evidence/survey_projection_adapter.py`, `backend/workbench/services/survey_consumer_service.py`, `backend/workbench/providers/builtin/survey.json`, `backend/workbench/agent/context_tools.py`, `backend/workbench/agent/notebook/evidence.py`, `tests/test_v189_survey_central_consumer.py`, `tests/test_v189_consumer_coverage.py`, `tests/test_v189_consumer_catalog_contract.py`, `docs/superpowers/objectives/2026-08-20-v1.8.9-p1-survey-central-source-objective.md`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-p1-survey-central-source.md`, `docs/superpowers/handoff/2026-08-20-v1.8.9-p1-survey-central-source-handoff.md`
- Allowed paths: `backend/workbench/evidence/survey_projection_adapter.py`, `backend/workbench/services/survey_consumer_service.py`, `backend/workbench/providers/builtin/survey.json`, `backend/workbench/agent/context_tools.py`, `backend/workbench/agent/notebook/evidence.py`, `tests/test_v189_survey_central_consumer.py`, `tests/test_v189_consumer_coverage.py`, `tests/test_v189_consumer_catalog_contract.py`, `docs/superpowers/objectives/2026-08-20-v1.8.9-p1-survey-central-source-objective.md`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-p1-survey-central-source.md`, `docs/superpowers/handoff/2026-08-20-v1.8.9-p1-survey-central-source-handoff.md`
- Protected paths: `backend/workbench/predictive_research`, `backend/workbench/data_operations.py`, `backend/workbench/app.py`, `frontend/src`
- Dependencies: `v1-8-9-contract-lock`, `v1-8-9-p1-classification-central-consumer`
- Tests: `PYTHONPATH=backend .venv/bin/pytest tests/test_v189_survey_central_consumer.py -q`
- Known gates: `report_http_browser_provider_full_release_not_verified`, `no_estimator_or_variance_semantics_changes`

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

### v1-8-4-agent-model-composition (2026-07-31T02:50:00.000Z)

Completed formal devline v1-8-4-agent-model-composition; final_state=COMPLETED; failure_lesson_keys=action-mode-route-enforcement, agent-covariance-interpretation-guardrail, agent-provider-and-tool-boundaries, bounded-model-specification-evidence, bounded-node-evidence-visibility, browser-blocked-run-lineage-identity, browser-policy-blocked-ui-acceptance, canonical-terminal-inspection-reuse, checkpoint-host-gate-separation, closing-event-timestamp-must-follow-the-incident, coefficient-batch-limit-protocol, covariance-comparison-interpretation-boundary, declared-white-test-post-estimation, derive-workflow-artifacts-server-side, existing-genesis-route-tests-failed, failed-inspection-retry, fms-event-enums-must-match-contract, fms-event-input-must-be-repository-relative, formal-event-redaction-text-ambiguity, formal-event-requires-real-evidence-digest, genesis-draft-url-visibility, genesis-draft-visibility-regression, global-agent-model-figure-evidence, global-agent-numeric-evidence-transcription, global-agent-workflow-answer-path, historical-proposal-terminal-message, inherited-suite-failures-must-be-baselined, notebook-persisted-lifecycle, notebook-planner-must-recover-to-server-pinned-rerun-target, notebook-planner-proposes-rerun-outside-active-head-lineage, notebook-planning-deadline-must-be-explicit-and-user-aligned, notebook-planning-evidence-admission, notebook-planning-exceeds-visible-timeout-without-terminal-state, notebook-workflow-dependency-shape-correction, notebook-workflow-evidence-bridge, panel-workflow-model-composition, persisted-draft-hydration-before-empty, planning-elapsed-counter-resets-on-remount, post-estimation-must-reproduce-declared-covariance, post-estimation-requires-explicit-step, predictor-residual-diagnostic-evidence, preexisting-backend-suite-failures, progress-clock-anchors-to-attempt, proposal-ready-boundary-updates-call-count, proposal-ready-terminal-state, provider-catalog-expectation-mismatch, provider-catalog-test-alignment, real-run-tests-must-claim-a-clean-slot, rescope-leaf-path-depth, separate-existing-route-failure, structured-evidence-not-prose-token, verified-categorical-indicator-reuse, white-test-auxiliary-rank-stability, white-test-own-rank-policy, workflow-branch-covariance-preservation, workflow-pin-registry-artifact-identity

### v1-8-3-integration-acceptance (2026-07-28T12:11:00.000Z)

Completed formal devline v1-8-3-integration-acceptance; final_state=COMPLETED; failure_lesson_keys=formal-cli-command-surface, formal-scope-narrowing, supported-host-containment-required

### v1-8-3-mem3-memory-curator-exact-baseline (2026-07-27T11:35:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator-exact-baseline; final_state=COMPLETED; failure_lesson_keys=curator-contract-first, review-api-awaits-response
