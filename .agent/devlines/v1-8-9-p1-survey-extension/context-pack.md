# Frozen Context Pack

Line: `v1-8-9-p1-survey-extension`
Baseline SHA: `05362b5697e10eb25fd219da003641f96eeec082`

## Objective
# Workbench v1.8.9 P1 Complex Survey Extension Objective

Extend the existing family-agnostic survey variance engine through real
workflow estimation hooks for Logit, Probit, and Poisson. The implementation
must use the declared sampling design and the same variance semantics as the
existing OLS path, including Taylor/linearization or replicate weights,
design degrees of freedom, lonely-PSU/subpopulation policy, design effect,
effective sample size, and explicit replicate failure handling.

The capability registry and UI must not advertise a family as survey-capable
unless the estimator path actually applies the survey variance result. Any
unsupported family/design combination must be typed blocked or unavailable;
never fall back to naive model-based standard errors while retaining survey
labels.

This line is limited to survey design/estimation adapters and their tests. It
does not add new model families, change central Agent/Notebook routing, call
an external provider, or claim browser/full-gate/release evidence.

The exact estimation outputs must retain coefficient-level variance source,
design df, confidence intervals, p-values, survey metadata, and artifact
provenance so Agent/Notebook/Report consumers can distinguish survey results
from ordinary model results.

## Boundary
- Affected paths: `docs/superpowers/objectives/2026-08-19-v1.8.9-p1-survey-extension-objective.md`, `backend/workbench/engine/stages/estimation.py`, `backend/workbench/survey/design.py`, `backend/workbench/survey/engine.py`, `backend/workbench/survey/replicates.py`, `backend/workbench/survey/adapters.py`, `backend/workbench/engine/replicate_combine/survey_adapter.py`, `backend/workbench/agent/workflow_contracts.py`, `backend/workbench/engine/capabilities.py`, `tests/test_survey_glm_family_wiring_v189.py`, `tests/test_survey_design_engine_v187.py`, `tests/test_survey_design_composition_v187.py`, `tests/test_survey_composition_limits_v187.py`, `tests/test_survey_report_visibility_v187.py`, `docs/superpowers/handoff/2026-08-19-v1.8.9-p1-survey-extension-handoff.md`, `.agent/devlines/v1-8-9-p1-survey-extension/RETROSPECTIVE.md`, `.agent/devlines/v1-8-9-p1-survey-extension/context-pack.manifest.json`, `.agent/devlines/v1-8-9-p1-survey-extension/context-pack.md`, `.agent/devlines/v1-8-9-p1-survey-extension/events.jsonl`, `.agent/devlines/v1-8-9-p1-survey-extension/events.jsonl.anchor`
- Allowed paths: `docs/superpowers/objectives/2026-08-19-v1.8.9-p1-survey-extension-objective.md`, `backend/workbench/engine/stages/estimation.py`, `backend/workbench/survey/design.py`, `backend/workbench/survey/engine.py`, `backend/workbench/survey/replicates.py`, `backend/workbench/survey/adapters.py`, `backend/workbench/engine/replicate_combine/survey_adapter.py`, `backend/workbench/agent/workflow_contracts.py`, `backend/workbench/engine/capabilities.py`, `tests/test_survey_glm_family_wiring_v189.py`, `tests/test_survey_design_engine_v187.py`, `tests/test_survey_design_composition_v187.py`, `tests/test_survey_composition_limits_v187.py`, `tests/test_survey_report_visibility_v187.py`, `docs/superpowers/handoff/2026-08-19-v1.8.9-p1-survey-extension-handoff.md`, `.agent/devlines/v1-8-9-p1-survey-extension/RETROSPECTIVE.md`, `.agent/devlines/v1-8-9-p1-survey-extension/context-pack.manifest.json`, `.agent/devlines/v1-8-9-p1-survey-extension/context-pack.md`, `.agent/devlines/v1-8-9-p1-survey-extension/events.jsonl`, `.agent/devlines/v1-8-9-p1-survey-extension/events.jsonl.anchor`
- Protected paths: `backend/workbench/agent/http`, `backend/workbench/http`, `backend/workbench/predictive_research`, `frontend/src`, `scripts/gate.sh`
- Dependencies: `v1-8-9-foundation-integration`
- Tests: `PYTHONPATH=backend .venv/bin/python -m pytest tests/test_survey_glm_family_wiring_v189.py tests/test_survey_design_engine_v187.py tests/test_survey_design_composition_v187.py tests/test_survey_composition_limits_v187.py tests/test_survey_report_visibility_v187.py -q`, `PYTHONPATH=backend .venv/bin/python -m compileall -q backend/workbench tests`, `git diff --check`
- Known gates: `external survey oracle/browser/provider/full gate/release remain separate`, `unsupported family/design must remain blocked`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
### v1-8-8-statistical-truth-cleanup (2026-08-13T10:11:25.000Z)

Completed formal devline v1-8-8-statistical-truth-cleanup; final_state=COMPLETED; failure_lesson_keys=none

### v1-8-3-integration-acceptance (2026-07-28T12:11:00.000Z)

Completed formal devline v1-8-3-integration-acceptance; final_state=COMPLETED; failure_lesson_keys=formal-cli-command-surface, formal-scope-narrowing, supported-host-containment-required

### v1-8-4-agent-evidence-loop (2026-07-28T15:52:01.000Z)

Completed formal devline v1-8-4-agent-evidence-loop; final_state=COMPLETED; failure_lesson_keys=agent-completed-operation-evidence-boundary, public-artifact-aggregate-budget

### v1-8-3-mem3-memory-curator-exact-baseline (2026-07-27T11:35:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator-exact-baseline; final_state=COMPLETED; failure_lesson_keys=curator-contract-first, review-api-awaits-response

### v1-8-3-mem3-memory-curator (2026-07-27T11:10:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator; final_state=CLOSED; failure_lesson_keys=none

### v1-8-8-agent-chain-hardening (2026-08-10T01:59:47.000Z)

Completed formal devline v1-8-8-agent-chain-hardening; final_state=COMPLETED; failure_lesson_keys=host-gate-calendar-and-projection, host-gate-integration-before-claim, manual-browser-coverage-gap, qa-runner-is-not-cryptographic-witness, report-upstream-retry-visible, typed-failure-fail-closed

### v1-8-8-p7-agent-adoption (2026-08-09T03:20:32.000Z)

Completed formal devline v1-8-8-p7-agent-adoption; final_state=COMPLETED; failure_lesson_keys=browser-report-remains-not-verified, declaration-derived-option-boundaries, design-diagnostic-neutral-envelope, generated-tool-schema-runtime-validation, p7-artifact-identity-preserves-repeatability, parent-workflow-owns-child-vocabulary, workflow-errors-preserve-step-cause

### p6-p7-capability-adoption (2026-08-09T02:05:00.000Z)

Completed formal devline p6-p7-capability-adoption; final_state=COMPLETED; failure_lesson_keys=focused-suite-root-cwd, formal-cli-schema-before-invocation, formal-context-pack-path, host-sandbox-gate-classification, p7-adapter-request-boundary, p7-frame-independent-fixture, p7-live-registry-guard, p7-recursive-request-safety, p7-result-contract-source, p7-result-projection-and-envelope, p7-transitive-dependency-scope, registry-test-root-path

### p4-data-management (2026-08-08T23:58:00.000Z)

Completed formal devline p4-data-management; final_state=COMPLETED; failure_lesson_keys=branch-local-schema-projection, execute-provider-handler-after-projection, formal-event-vocabulary, formal-start-normalized-tags, mutation-derived-values, mutation-live-projection, mutation-no-silent-dataset-omission, p4-contract-first, preserve-existing-branch-return, review-live-registry-api, strip-composition-fields-at-adapter, typed-adapter-parameter-boundary, typed-preview-field-fidelity

### p3-capability-registration (2026-08-08T21:11:06.000Z)

Completed formal devline p3-capability-registration; final_state=COMPLETED; failure_lesson_keys=formal-event-schema-values, query-live-fields-before-verification, stage-worktree-from-host, tdd-red-before-implementation, use-formal-event-hash-schema
