# Frozen Context Pack

Line: `v1-8-9-p0-legacy-consumer-gate-migration`
Baseline SHA: `91ee6a05eab2a1892844c8a3057e1e607359a29e`

## Objective
# Workbench v1.8.9 P0 legacy consumer gate migration

## Objective

Migrate the legacy full-gate tests that still assume v1.8.8 raw-result,
unbound-report, or untyped proposal-store behavior to the v1.8.9 typed
server-owned contracts. The migration must make the tests exercise the current
owner-bound evidence and proposal capability boundaries; it must not restore a
raw model-result fallback, accept an unbound report mapping, or make an absent
server authority look available.

## Success criteria

1. The focused legacy consumer/report/lifecycle/golden command passes or
   records only explicitly expected typed-unavailable outcomes with stable
   evidence.
2. ARMA-GARCH report tests use the existing typed report-document adapter and
   server-owned test fixture.
3. Consumer projection tests use the central typed reader rather than the
   removed `_model_results` hook.
4. Analysis-loop lifecycle tests construct a server-issued proposal-store
   capability through the supported test seam.
5. Golden snapshots record the current typed report/evidence contract without
   hiding or deleting error states.
6. No production trust boundary is weakened and no arbitrary path, executor,
   raw mapping, or caller-owned authority is admitted.

## Non-goals

- No new statistical estimator or model family.
- No report renderer fallback to raw mappings.
- No production host/provider/browser/release acceptance claim.

## Required verification

```text
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend .venv/bin/pytest -p no:cacheprovider tests/models/arma_garch/test_deliverables.py tests/predictive_research/test_consumer_projection_v186.py tests/test_agent_analysis_loop_lifecycle.py tests/test_engine_golden.py tests/test_statistical_exploration_golden.py -q --disable-warnings
```

Also run selected-file compileall, `git diff --check`, and the formal devline
verification/retrospective. Full host gate, browser/provider acceptance, and
release remain separate gates.

## Boundary
- Affected paths: `tests/models/arma_garch/test_deliverables.py`, `tests/predictive_research/test_consumer_projection_v186.py`, `tests/test_agent_analysis_loop_lifecycle.py`, `tests/test_engine_golden.py`, `tests/golden/binary_logit.json`, `tests/golden/blocked_missing_column.json`, `tests/golden/continuous_ols.json`, `tests/golden/count_poisson.json`, `tests/golden/cs_did_clustered.json`, `tests/golden/cs_did_honest.json`, `tests/golden/cs_did_staggered.json`, `tests/golden/dcdh_nonabsorbing.json`, `tests/golden/did_staggered.json`, `tests/golden/did_two_by_two.json`, `tests/golden/explicit_logit.json`, `tests/golden/imputation.json`, `tests/golden/iv_2sls.json`, `tests/golden/panel.json`, `tests/golden/sa_did_honest.json`, `tests/golden/sa_did_staggered.json`, `docs/superpowers/objectives/2026-08-20-v1.8.9-p0-legacy-consumer-gate-migration-objective.md`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-p0-legacy-consumer-gate-migration.md`, `docs/superpowers/handoff/2026-08-20-v1.8.9-p0-legacy-consumer-gate-migration-handoff.md`
- Allowed paths: `tests/models/arma_garch/test_deliverables.py`, `tests/predictive_research/test_consumer_projection_v186.py`, `tests/test_agent_analysis_loop_lifecycle.py`, `tests/test_engine_golden.py`, `tests/golden/binary_logit.json`, `tests/golden/blocked_missing_column.json`, `tests/golden/continuous_ols.json`, `tests/golden/count_poisson.json`, `tests/golden/cs_did_clustered.json`, `tests/golden/cs_did_honest.json`, `tests/golden/cs_did_staggered.json`, `tests/golden/dcdh_nonabsorbing.json`, `tests/golden/did_staggered.json`, `tests/golden/did_two_by_two.json`, `tests/golden/explicit_logit.json`, `tests/golden/imputation.json`, `tests/golden/iv_2sls.json`, `tests/golden/panel.json`, `tests/golden/sa_did_honest.json`, `tests/golden/sa_did_staggered.json`, `docs/superpowers/objectives/2026-08-20-v1.8.9-p0-legacy-consumer-gate-migration-objective.md`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-p0-legacy-consumer-gate-migration.md`, `docs/superpowers/handoff/2026-08-20-v1.8.9-p0-legacy-consumer-gate-migration-handoff.md`
- Protected paths: `backend/workbench/reporting.py`, `backend/workbench/evidence`, `backend/workbench/analysis_loop/lifecycle.py`, `backend/workbench/agent/orchestrator.py`, `backend/workbench/http/runs_routes.py`, `backend/workbench/predictive_research/consumer_projection.py`, `backend/workbench/engine/stages/report.py`
- Dependencies: none
- Tests: `PYTHONPATH=backend .venv/bin/python -m pytest -p no:cacheprovider tests/models/arma_garch/test_deliverables.py tests/predictive_research/test_consumer_projection_v186.py tests/test_agent_analysis_loop_lifecycle.py tests/test_engine_golden.py tests/test_statistical_exploration_golden.py -q --disable-warnings`, `PYTHONPATH=backend .venv/bin/python -m compileall -q backend/workbench tests`, `git diff --check`
- Known gates: `browser/provider/production host identity/multi-worker/restart/full host gate/release remain NOT VERIFIED`

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

### v1-8-9-p0-agent-compiler-remediation-5 (2026-08-19T02:35:17.000Z)

Completed formal devline v1-8-9-p0-agent-compiler-remediation-5; final_state=COMPLETED; failure_lesson_keys=os-boundary-probes-need-controlled-sandbox-access

### v1-8-9-p0-workflow-truth-remediation-6 (2026-08-16T16:15:00.000Z)

Completed formal devline v1-8-9-p0-workflow-truth-remediation-6; final_state=COMPLETED; failure_lesson_keys=formal-output-registration-transaction, register-child-run-model-artifacts, runtime-fixture-model-preconditions, use-declared-model-minimum

### v1-8-9-p0-legacy-compilation-authority-cutover (2026-08-16T14:30:00.000Z)

Completed formal devline v1-8-9-p0-legacy-compilation-authority-cutover; final_state=COMPLETED; failure_lesson_keys=legacy-authority-red-before-implementation, legacy-cutover-keeps-host-dependency-explicit

### v1-8-9-p0-workflow-truth-remediation-5 (2026-08-16T13:35:00.000Z)

Completed formal devline v1-8-9-p0-workflow-truth-remediation-5; final_state=COMPLETED; failure_lesson_keys=production-host-integration-boundary, runtime-artifact-no-follow, workflow-remediation-5-red-before-fix

### v1-8-9-p0-evidence-core-remediation-7 (2026-08-16T12:56:51.000Z)

Completed formal devline v1-8-9-p0-evidence-core-remediation-7; final_state=COMPLETED; failure_lesson_keys=evidence-host-trust-root, typed-timeout-boundary
