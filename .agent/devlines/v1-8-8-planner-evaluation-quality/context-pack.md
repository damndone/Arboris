# Frozen Context Pack

Line: `v1-8-8-planner-evaluation-quality`
Baseline SHA: `d2557a9a0dfe9a861dad98e9b81977461e7cbcda`

## Objective
# v1.8.8 planner evaluation and quality closeout objective

## Objective

Add a declaration-derived natural-language planner evaluation system that
measures ordinary prompts without turning a fixed prompt corpus into product
logic. Cover normal, ambiguous, missing-input, false-causal, and prompt-
injection cases; score typed operation choice, bindings, options, refusal
reasons, and invented identities. Keep deterministic structural checks in CI
and run stochastic provider benchmarks as a separate release gate with an
overall correctness threshold of 95% and a dangerous-request safe-refusal
threshold of 100%.

Close three adjacent v1.8.8 quality gaps in the same source tree:

- add a convergent Hurdle negative-binomial generic-workflow fixture while
  retaining the existing non-convergence safety fixture;
- replace P7 family-internal operation branches with declaration-keyed handler
  maps without adding orchestrator dispatch;
- remove Workbench-owned React `act(...)`, dependency-deprecation, and
  avoidable statistical numerical warnings, while classifying rather than
  suppressing warnings owned by third-party libraries or intentionally
  degenerate safety fixtures.

## Boundaries

- Evaluation cases and expected identities derive from live declarations.
- Prompt variants are data for evaluation only and never enter production
  routing, keyword rules, or hard-coded model selection.
- Hidden/holdout variants must differ from public examples and must not be read
  by the planner under evaluation.
- Provider output is admitted only through the existing typed planner and
  contract boundaries; the evaluator does not repair malformed output.
- No warning is globally ignored. Statistical warnings are either converted
  into explicit typed evidence/rejection or retained with a documented owner.
- Do not weaken P0/P1/P2/P3 contracts, user confirmation, provenance, or
  fail-closed behavior.
- No external witness provider, push, PR, merge, tag, or release.

## Acceptance

- A registry mutation automatically changes the planner-evaluation denominator
  and generated case inventory without editing a second ID list.
- Every live reachable capability receives all five scenario classes, with
  holdout variation and leakage checks.
- The deterministic evaluator rejects wrong operations, malformed bindings or
  options, unsafe causal claims, unsafe injection compliance, and invented
  run/node/artifact IDs.
- The provider benchmark reports per-capability and per-scenario results,
  confidence intervals, exact provider/model/configuration, immutable input and
  output digests, and exits nonzero below the approved thresholds.
- Browser confirmation remains limited to representative high-risk paths.
- Hurdle negative-binomial has both one successful persisted generic workflow
  outcome and one explicit non-convergence outcome.
- P7 handler maps are declaration-derived and mutation-proven; unknown IDs fail
  closed and no orchestrator dispatch file changes.
- Workbench-owned warnings targeted by this line are absent from focused tests;
  remaining upstream or intentional warnings are explicitly inventoried.
- Focused backend/frontend tests, typecheck, formal verification, 64-operation
  batch execution, and the host full gate pass on the final source commit.

## Boundary
- Affected paths: `docs/superpowers/objectives/2026-08-13-v1.8.8-planner-evaluation-and-quality-objective.md`, `docs/superpowers/specs/2026-08-13-v1.8.8-planner-evaluation-and-quality-design.md`, `backend/workbench/agent/planner_evaluation.py`, `backend/workbench/agent/p7_pack_adapters.py`, `backend/workbench/engine/packs/glm_extensions/runtime.py`, `scripts/planner_benchmark.py`, `tests/evaluation/planner`, `tests/fixtures/evaluation/planner`, `tests/test_glm_extensions_pack.py`, `tests/test_p7_workflow_integration.py`, `tests/test_p7_adoption_calls.py`, `tests/test_p7_adoption_registry.py`, `frontend/src/report/ReportView.test.tsx`, `frontend/src/workbench/WorkbenchRouteContainer.test.tsx`
- Allowed paths: `docs/superpowers/objectives/2026-08-13-v1.8.8-planner-evaluation-and-quality-objective.md`, `docs/superpowers/specs/2026-08-13-v1.8.8-planner-evaluation-and-quality-design.md`, `backend/workbench/agent/planner_evaluation.py`, `backend/workbench/agent/p7_pack_adapters.py`, `backend/workbench/engine/packs/glm_extensions/runtime.py`, `scripts/planner_benchmark.py`, `tests/evaluation/planner`, `tests/fixtures/evaluation/planner`, `tests/test_glm_extensions_pack.py`, `tests/test_p7_workflow_integration.py`, `tests/test_p7_adoption_calls.py`, `tests/test_p7_adoption_registry.py`, `frontend/src/report/ReportView.test.tsx`, `frontend/src/workbench/WorkbenchRouteContainer.test.tsx`
- Protected paths: `backend/workbench/agent/orchestrator.py`, `backend/workbench/orchestrator.py`
- Dependencies: `v1-8-8-statistical-truth-cleanup`, `v1-8-8-final-integration`
- Tests: `cd backend && PYTHONPATH=$PWD ../.venv/bin/python -m pytest ../tests/evaluation/planner ../tests/test_glm_extensions_pack.py ../tests/test_p7_workflow_integration.py ../tests/test_p7_adoption_calls.py ../tests/test_p7_adoption_registry.py -q`, `cd frontend && npm test -- --run src/report/ReportView.test.tsx src/workbench/WorkbenchRouteContainer.test.tsx`, `cd frontend && npm run typecheck`
- Known gates: `Provider benchmark requires configured DeepSeek credentials and is a release gate, not deterministic CI.`, `Host full gate must run outside the managed agent sandbox.`, `Third-party deprecations and intentional degenerate-fixture warnings may remain only with explicit ownership evidence.`

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

### v1-8-4-agent-model-composition (2026-07-31T02:50:00.000Z)

Completed formal devline v1-8-4-agent-model-composition; final_state=COMPLETED; failure_lesson_keys=action-mode-route-enforcement, agent-covariance-interpretation-guardrail, agent-provider-and-tool-boundaries, bounded-model-specification-evidence, bounded-node-evidence-visibility, browser-blocked-run-lineage-identity, browser-policy-blocked-ui-acceptance, canonical-terminal-inspection-reuse, checkpoint-host-gate-separation, closing-event-timestamp-must-follow-the-incident, coefficient-batch-limit-protocol, covariance-comparison-interpretation-boundary, declared-white-test-post-estimation, derive-workflow-artifacts-server-side, existing-genesis-route-tests-failed, failed-inspection-retry, fms-event-enums-must-match-contract, fms-event-input-must-be-repository-relative, formal-event-redaction-text-ambiguity, formal-event-requires-real-evidence-digest, genesis-draft-url-visibility, genesis-draft-visibility-regression, global-agent-model-figure-evidence, global-agent-numeric-evidence-transcription, global-agent-workflow-answer-path, historical-proposal-terminal-message, inherited-suite-failures-must-be-baselined, notebook-persisted-lifecycle, notebook-planner-must-recover-to-server-pinned-rerun-target, notebook-planner-proposes-rerun-outside-active-head-lineage, notebook-planning-deadline-must-be-explicit-and-user-aligned, notebook-planning-evidence-admission, notebook-planning-exceeds-visible-timeout-without-terminal-state, notebook-workflow-dependency-shape-correction, notebook-workflow-evidence-bridge, panel-workflow-model-composition, persisted-draft-hydration-before-empty, planning-elapsed-counter-resets-on-remount, post-estimation-must-reproduce-declared-covariance, post-estimation-requires-explicit-step, predictor-residual-diagnostic-evidence, preexisting-backend-suite-failures, progress-clock-anchors-to-attempt, proposal-ready-boundary-updates-call-count, proposal-ready-terminal-state, provider-catalog-expectation-mismatch, provider-catalog-test-alignment, real-run-tests-must-claim-a-clean-slot, rescope-leaf-path-depth, separate-existing-route-failure, structured-evidence-not-prose-token, verified-categorical-indicator-reuse, white-test-auxiliary-rank-stability, white-test-own-rank-policy, workflow-branch-covariance-preservation, workflow-pin-registry-artifact-identity

### v1-8-4-open-incidents-remediation (2026-07-31T04:08:00.000Z)

Completed formal devline v1-8-4-open-incidents-remediation; final_state=COMPLETED; failure_lesson_keys=closing-evidence-must-postdate-the-work

### v1-8-3-document-authority-consolidation (2026-07-26T03:30:00.000Z)

Completed formal devline v1-8-3-document-authority-consolidation; final_state=COMPLETED; failure_lesson_keys=none

### wo-b-model-pack (2026-07-20T17:44:54.000Z)

Completed formal devline wo-b-model-pack; final_state=CLOSED; failure_lesson_keys=versioned-public-result-contract
