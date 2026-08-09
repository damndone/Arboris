# Frozen Context Pack

Line: `p5-reachability-gaps`
Baseline SHA: `ebba33f18037d3569f3d39dae8773b21a870e6e5`

## Objective
# Arboris v1.8.8 P5 objective

Line: `p5-reachability-gaps`

Baseline: `ebba33f18037d3569f3d39dae8773b21a870e6e5`

Worktree: `/Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.8-p5`

Objective: close the 18 live P2 reachability gaps through typed, fail-closed `operation.multi_step` workflow contracts. Preserve the four existing direct natural-language operations and the two explicit closures. Keep the automatic eight-family statistical stage intact while adding named family execution with explicit evidence identity and multiple-comparison scope. Make data preparation control the dataset bound to downstream prediction, and admit the three prediction families, two time-series recipe families, and `model.auto` through live operation/contract projections.

Exact gaps:

`model.time_series.arma_garch`, `model.time_series.ets`, `model.auto`, `test.anova`, `test.chi_square`, `test.correlations`, `test.evidence`, `test.fisher_exact`, `test.nonparametric`, `test.rank_correlations`, `test.t_tests`, `prediction.prediction_lasso`, `prediction.prediction_ridge`, `prediction.prediction_random_forest`, `imputation.mice`, `resample.smote`, `resample.oversample`, `resample.undersample`.

Plan: [2026-08-08-v1.8.8-p5-reachability-gaps.md](/Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.8-p5/docs/superpowers/plans/2026-08-08-v1.8.8-p5-reachability-gaps.md)

Boundaries: backend contracts, workflow runtime/evidence, prediction/data preparation, tests, and formal-line records only. Do not touch frontend/P7, parent/P4/P6 worktrees, or perform push/PR/merge/tag/release actions.

Known gates and evidence requirements: strict red-green TDD; live mutation verification for every derived list and hard-code replacement; focused and relevant regression tests; full backend pytest from the repository root with only `tests/test_cs_did_oracle.py` and `tests/test_cs_did_clustering.py` ignored; host-terminal `bash scripts/gate.sh --full`; formal event verification and retrospective regeneration before line close.

Final acceptance: the live guard must report `(54, 4, 48, 52, 2, 0)`, with no gap IDs and only `code.execute` plus `data.column.cast` as explicit, reasoned exemptions. If live results differ, stop, investigate the projection identity, and update this objective/plan only with evidence from the live registry rather than guessing.

## Boundary
- Affected paths: `tests/test_workflow_seam.py`
- Allowed paths: `tests/test_workflow_seam.py`
- Protected paths: `frontend`
- Dependencies: none
- Tests: `focused capability/contract/statistical/data-preparation/prediction/workflow tests`, `full backend pytest --ignore=tests/test_cs_did_oracle.py --ignore=tests/test_cs_did_clustering.py`
- Known gates: `bash scripts/gate.sh --full (host terminal)`, `formal event verify + retrospective regeneration`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
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

### v1-8-4-agent-model-composition (2026-07-31T02:50:00.000Z)

Completed formal devline v1-8-4-agent-model-composition; final_state=COMPLETED; failure_lesson_keys=action-mode-route-enforcement, agent-covariance-interpretation-guardrail, agent-provider-and-tool-boundaries, bounded-model-specification-evidence, bounded-node-evidence-visibility, browser-blocked-run-lineage-identity, browser-policy-blocked-ui-acceptance, canonical-terminal-inspection-reuse, checkpoint-host-gate-separation, closing-event-timestamp-must-follow-the-incident, coefficient-batch-limit-protocol, covariance-comparison-interpretation-boundary, declared-white-test-post-estimation, derive-workflow-artifacts-server-side, existing-genesis-route-tests-failed, failed-inspection-retry, fms-event-enums-must-match-contract, fms-event-input-must-be-repository-relative, formal-event-redaction-text-ambiguity, formal-event-requires-real-evidence-digest, genesis-draft-url-visibility, genesis-draft-visibility-regression, global-agent-model-figure-evidence, global-agent-numeric-evidence-transcription, global-agent-workflow-answer-path, historical-proposal-terminal-message, inherited-suite-failures-must-be-baselined, notebook-persisted-lifecycle, notebook-planner-must-recover-to-server-pinned-rerun-target, notebook-planner-proposes-rerun-outside-active-head-lineage, notebook-planning-deadline-must-be-explicit-and-user-aligned, notebook-planning-evidence-admission, notebook-planning-exceeds-visible-timeout-without-terminal-state, notebook-workflow-dependency-shape-correction, notebook-workflow-evidence-bridge, panel-workflow-model-composition, persisted-draft-hydration-before-empty, planning-elapsed-counter-resets-on-remount, post-estimation-must-reproduce-declared-covariance, post-estimation-requires-explicit-step, predictor-residual-diagnostic-evidence, preexisting-backend-suite-failures, progress-clock-anchors-to-attempt, proposal-ready-boundary-updates-call-count, proposal-ready-terminal-state, provider-catalog-expectation-mismatch, provider-catalog-test-alignment, real-run-tests-must-claim-a-clean-slot, rescope-leaf-path-depth, separate-existing-route-failure, structured-evidence-not-prose-token, verified-categorical-indicator-reuse, white-test-auxiliary-rank-stability, white-test-own-rank-policy, workflow-branch-covariance-preservation, workflow-pin-registry-artifact-identity

### v1-8-3-document-authority-consolidation (2026-07-26T03:30:00.000Z)

Completed formal devline v1-8-3-document-authority-consolidation; final_state=COMPLETED; failure_lesson_keys=none

### v1-8-5-notebook-capability-admission (2026-08-01T22:35:30.000Z)

Completed formal devline v1-8-5-notebook-capability-admission; final_state=COMPLETED; failure_lesson_keys=notebook-admission-must-require-published-contract

### v1-8-5-c4-projection-registry (2026-08-01T21:58:07.000Z)

Completed formal devline v1-8-5-c4-projection-registry; final_state=COMPLETED; failure_lesson_keys=projection-registry-before-recipe-growth

### v1-8-5-c3-recipe-preflight-projection (2026-08-01T21:47:00.000Z)

Completed formal devline v1-8-5-c3-recipe-preflight-projection; final_state=COMPLETED; failure_lesson_keys=c3-gate-dedicated-basetemp, recipe-preflight-before-draft
