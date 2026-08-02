# Frozen Context Pack

Line: `v1-8-5-notebook-planning-stability`
Baseline SHA: `7c24890cda0c426bf589908bc6128626c0e5f763`

## Objective
# v1.8.5 Notebook planning stability objective

## Objective

Make source-bound Notebook planning reliably produce a typed option batch when
the server has already prepared the required bounded evidence, without adding
dataset-specific fallbacks or weakening proposal validation.

## Design boundary

- Reuse the existing baseline Evidence Pack; do not ask the provider to repeat
  completed inspections.
- When the baseline is complete, expose only the typed submission tool for the
  first provider turn and request that tool explicitly through the generic
  model request configuration.
- Keep inspection tools available when a real evidence gap remains.
- Preserve the long per-provider timeout and user cancellation; do not add a
  short aggregate deadline or silently execute a partial plan.
- Do not expose private reasoning content or treat it as user-visible evidence.
- Do not relax evidence, capability, execution-pin, or Draft validation.
- Do not retry a provider stream after it has produced provider activity but
  failed to yield a public completion; this avoids duplicate expensive calls.

## Acceptance

- A complete baseline Evidence Pack causes one typed submission turn and no
  inspection turn.
- A missing evidence record still permits a bounded inspection followed by a
  typed submission.
- Provider request configuration reaches the OpenAI-compatible wire payload.
- A stream containing only private reasoning activity is not retried as a new
  request, and still fails closed if no public completion arrives.
- Existing Notebook planning, provider, and contract tests remain green.
- Real DeepSeek Notebook planning is retried once through the Workbench UI and
  is reported as success or failure with its actual evidence.

## Boundary
- Affected paths: `docs/superpowers/specs/2026-08-01-v1.8.5-notebook-planning-stability-objective.md`, `backend/workbench/agent/notebook/planning_agent.py`, `backend/workbench/agent/model.py`, `backend/workbench/llm/client.py`, `tests/test_notebook_planning_agent.py`, `tests/test_llm_providers.py`
- Allowed paths: `docs/superpowers/specs/2026-08-01-v1.8.5-notebook-planning-stability-objective.md`, `backend/workbench/agent/notebook/planning_agent.py`, `backend/workbench/agent/model.py`, `backend/workbench/llm/client.py`, `tests/test_notebook_planning_agent.py`, `tests/test_llm_providers.py`
- Protected paths: `backend/workbench/http/notebook_routes.py`, `frontend/src`
- Dependencies: `v1-8-5-b2-time-series-default-targets`
- Tests: `LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/pytest -q tests/test_notebook_planning_agent.py tests/test_llm_providers.py`, `git diff --check`
- Known gates: `Do not use a short aggregate planning deadline; preserve user cancellation`, `Real DeepSeek browser regression is separate from deterministic tests`, `Full gate requires inactive Vite and a non-nested host for Darwin containment evidence`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
### v1-8-4-agent-model-composition (2026-07-31T02:50:00.000Z)

Completed formal devline v1-8-4-agent-model-composition; final_state=COMPLETED; failure_lesson_keys=action-mode-route-enforcement, agent-covariance-interpretation-guardrail, agent-provider-and-tool-boundaries, bounded-model-specification-evidence, bounded-node-evidence-visibility, browser-blocked-run-lineage-identity, browser-policy-blocked-ui-acceptance, canonical-terminal-inspection-reuse, checkpoint-host-gate-separation, closing-event-timestamp-must-follow-the-incident, coefficient-batch-limit-protocol, covariance-comparison-interpretation-boundary, declared-white-test-post-estimation, derive-workflow-artifacts-server-side, existing-genesis-route-tests-failed, failed-inspection-retry, fms-event-enums-must-match-contract, fms-event-input-must-be-repository-relative, formal-event-redaction-text-ambiguity, formal-event-requires-real-evidence-digest, genesis-draft-url-visibility, genesis-draft-visibility-regression, global-agent-model-figure-evidence, global-agent-numeric-evidence-transcription, global-agent-workflow-answer-path, historical-proposal-terminal-message, inherited-suite-failures-must-be-baselined, notebook-persisted-lifecycle, notebook-planner-must-recover-to-server-pinned-rerun-target, notebook-planner-proposes-rerun-outside-active-head-lineage, notebook-planning-deadline-must-be-explicit-and-user-aligned, notebook-planning-evidence-admission, notebook-planning-exceeds-visible-timeout-without-terminal-state, notebook-workflow-dependency-shape-correction, notebook-workflow-evidence-bridge, panel-workflow-model-composition, persisted-draft-hydration-before-empty, planning-elapsed-counter-resets-on-remount, post-estimation-must-reproduce-declared-covariance, post-estimation-requires-explicit-step, predictor-residual-diagnostic-evidence, preexisting-backend-suite-failures, progress-clock-anchors-to-attempt, proposal-ready-boundary-updates-call-count, proposal-ready-terminal-state, provider-catalog-expectation-mismatch, provider-catalog-test-alignment, real-run-tests-must-claim-a-clean-slot, rescope-leaf-path-depth, separate-existing-route-failure, structured-evidence-not-prose-token, verified-categorical-indicator-reuse, white-test-auxiliary-rank-stability, white-test-own-rank-policy, workflow-branch-covariance-preservation, workflow-pin-registry-artifact-identity

### v1-8-5-c1-regression-family-admission (2026-08-01T13:48:08.000Z)

Completed formal devline v1-8-5-c1-regression-family-admission; final_state=COMPLETED; failure_lesson_keys=family-column-fields-preserve-elementwise, family-contract-drives-source-schema-validation, family-input-validation-before-genesis, materialization-uses-family-contract-not-ols-heuristic, model-family-field-ownership-fail-closed, normalized-fms-tag-before-start, notebook-delegates-to-shared-family-contract, regression-family-contract-before-admission

### v1-8-5-b1-default-target-registry (2026-08-01T13:00:04.000Z)

Completed formal devline v1-8-5-b1-default-target-registry; final_state=COMPLETED; failure_lesson_keys=default-target-registry-needs-explicit-scope-and-vocabulary, memory-default-source-roundtrip-exact-keys, memory-projection-versioned-authority-boundary

### v1-8-4-reopened-incident-truth (2026-07-31T08:10:00.000Z)

Completed formal devline v1-8-4-reopened-incident-truth; final_state=COMPLETED; failure_lesson_keys=full-gate-requires-non-nested-seatbelt, gate-requires-non-nested-sandbox

### v1-8-4-agent-evidence-loop (2026-07-28T15:52:01.000Z)

Completed formal devline v1-8-4-agent-evidence-loop; final_state=COMPLETED; failure_lesson_keys=agent-completed-operation-evidence-boundary, public-artifact-aggregate-budget

### v1-8-3-integration-acceptance (2026-07-28T12:11:00.000Z)

Completed formal devline v1-8-3-integration-acceptance; final_state=COMPLETED; failure_lesson_keys=formal-cli-command-surface, formal-scope-narrowing, supported-host-containment-required

### v1-8-3-mem3-memory-curator-exact-baseline (2026-07-27T11:35:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator-exact-baseline; final_state=COMPLETED; failure_lesson_keys=curator-contract-first, review-api-awaits-response

### v1-8-3-mem3-memory-curator (2026-07-27T11:10:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator; final_state=CLOSED; failure_lesson_keys=none

### v1-8-4-open-incidents-remediation (2026-07-31T04:08:00.000Z)

Completed formal devline v1-8-4-open-incidents-remediation; final_state=COMPLETED; failure_lesson_keys=closing-evidence-must-postdate-the-work

### v1-8-3-cf4-notebook-planner-projection-r1 (2026-07-26T23:16:01.000Z)

Completed formal devline v1-8-3-cf4-notebook-planner-projection-r1; final_state=COMPLETED; failure_lesson_keys=bounded-planner-projection-inputs, consumer-admission-facts-align-across-contracts, scope-aware-bound-option-revalidation, tdd-red-before-planner-projection
