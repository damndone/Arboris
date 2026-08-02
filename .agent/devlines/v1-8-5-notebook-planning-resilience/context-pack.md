# Frozen Context Pack

Line: `v1-8-5-notebook-planning-resilience`
Baseline SHA: `47f27eb9b39c42ef09a71f921826506e623b8b2f`

## Objective
# v1.8.5 Notebook planning resilience objective

## Objective

Test the Notebook planning boundary against plausible provider, transport,
planner, and cancellation failures, then fix only general defects proved by
those tests. The result must remain typed, evidence-bound, fail-closed, and
safe to retry without silently duplicating provider work.

This is a resilience slice on top of the existing Notebook planning stability
slice. It does not add model families, change the frontend, expose private
chain-of-thought, or add dataset-specific behavior.

## Failure matrix

The test harness must cover at least:

1. provider returns no event until the idle boundary;
2. provider emits private reasoning activity, then disconnects or ends without
   public text/tool completion;
3. provider emits malformed JSON, malformed tool-call fragments, an unknown
   tool, or a tool call with invalid arguments;
4. provider emits duplicate done/tool events or repeats a submission;
5. provider disconnects after a valid partial tool call and after a valid
   complete submission;
6. caller cancellation races with provider completion and with timeout;
7. evidence is incomplete, contradictory, stale, oversized, or contains an
   unsupported artifact type;
8. a proposal is submitted with missing source columns, invalid memory
   defaults, duplicate option IDs, too many options, or an invalid risk/
   evidence field.

Each case must assert an observable terminal state, bounded provider-call
count, no execution side effect, and a diagnostic that distinguishes provider
failure, cancellation, timeout, malformed output, and contract rejection.

## Invariants

- A request is never retried after a provider activity, completed tool call, or
  user cancellation unless the retry policy explicitly proves no actionable
  provider progress occurred.
- Invalid or ambiguous model output never becomes a persisted option batch.
- A valid option batch is persisted at most once per planning attempt.
- Cancellation is idempotent and wins over a late provider completion.
- Memory may fill only registered fields after required source fields are
  declared; it cannot invent dataset columns or model inputs.
- The planner never executes a proposal. It only produces a validated option
  batch for the existing confirmation and authorization lifecycle.
- Private reasoning remains internal; only observable activity stages and
  safe diagnostics are exposed.

## Test-first delivery

1. Add deterministic fault-injection adapters and failing tests for the matrix
   above. Record at least one failure before each production fix.
2. Fix the smallest provider-neutral or adapter-boundary defect that explains
   the failure. Do not loosen validation to make malformed responses pass.
3. Run the focused Notebook/provider/memory suite and inspect provider-call
   counts, terminal states, and persisted batches.
4. Run one real Workbench DeepSeek request through the visible Notebook UI;
   verify success, cancellation, and failure presentation without using a
   backend upload shortcut.

## Acceptance and non-claims

Acceptance requires the fault-injection matrix to pass, no duplicate provider
calls in the tested races, the focused suite to remain green, and one real
DeepSeek Notebook planning request to complete or fail with an actionable
diagnosis. This slice does not claim every provider is compatible, that all
complex prompts complete within a fixed wall-clock time, or that full release,
frontend, deployment, or native-containment gates have passed.

## Boundary
- Affected paths: `docs/superpowers/specs/2026-08-01-v1.8.5-notebook-planning-resilience-objective.md`, `backend/workbench/agent/model.py`, `backend/workbench/agent/notebook/planning_agent.py`, `backend/workbench/llm/client.py`, `tests/test_llm_providers.py`, `tests/test_notebook_planning_agent.py`
- Allowed paths: `docs/superpowers/specs/2026-08-01-v1.8.5-notebook-planning-resilience-objective.md`, `backend/workbench/agent/model.py`, `backend/workbench/agent/notebook/planning_agent.py`, `backend/workbench/llm/client.py`, `tests/test_llm_providers.py`, `tests/test_notebook_planning_agent.py`
- Protected paths: `frontend/src`, `backend/workbench/http/notebook_routes.py`, `backend/workbench/storage`
- Dependencies: `v1-8-5-notebook-planning-stability@e2453b3`
- Tests: `LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/pytest -q tests/test_notebook_planning_agent.py tests/test_llm_providers.py tests/test_notebook_memory_defaults.py`, `LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/pytest -q tests/test_no_exercise_specific_naming.py`, `real Workbench UI DeepSeek Notebook planning acceptance with tab kept open`
- Known gates: `full repository gate is separate; do not claim full release evidence`, `Darwin native containment remains host-dependent and out of scope`, `provider latency is not failure unless idle boundary or total budget is crossed`

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

### v1-8-5-c4-projection-registry (2026-08-01T21:58:07.000Z)

Completed formal devline v1-8-5-c4-projection-registry; final_state=COMPLETED; failure_lesson_keys=projection-registry-before-recipe-growth

### v1-8-5-c3-recipe-preflight-projection (2026-08-01T21:47:00.000Z)

Completed formal devline v1-8-5-c3-recipe-preflight-projection; final_state=COMPLETED; failure_lesson_keys=c3-gate-dedicated-basetemp, recipe-preflight-before-draft
