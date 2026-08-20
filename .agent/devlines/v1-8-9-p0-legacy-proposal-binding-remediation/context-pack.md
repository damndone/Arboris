# Frozen Context Pack

Line: `v1-8-9-p0-legacy-proposal-binding-remediation`
Baseline SHA: `d472ab09bb00bc0ddfd6ee4ee5a84af32383ac91`

## Objective
# Workbench v1.8.9 P0 Legacy Agent Proposal-Binding Remediation Objective

Close the remaining legacy Agent confirmation proposal-binding bypass found by
the independent code-quality review. A retained legacy confirmation handle
must be server-bound to the exact proposal identity at proposal/compile/
confirmation creation time, and execution must accept only that persisted
server-owned binding.

Required outcomes:

- `ServerConfirmationReceiptV1` persists and validates proposal id, revision,
  fingerprint, semantic plan hash, actor, session, and project identity.
- Proposal, compilation, and confirmation creation bind the complete identity
  on the server; execution never accepts caller-supplied identity as authority.
- A first claim whose proposal identity mismatches the retained confirmation
  fails closed before compiler execution and does not create a binding.
- The exact same proposal succeeds once its server binding is valid; replay,
  cross-scope, serialization, and tamper cases fail closed before execution.
- Compatibility response shapes remain separate from the security/correctness
  gate. No Report/data/classification/survey or central unrelated paths change.

## Boundary

- Affected paths: `backend/workbench/http/agent_routes.py`,
  `backend/workbench/agent/orchestrator.py`,
  `backend/workbench/agent/proposals.py`,
  `backend/workbench/agent/compiler.py`,
  `tests/test_v189_legacy_route_authority.py`,
  `tests/test_v189_legacy_proposal_binding.py`
- Allowed paths: same as affected paths
- Protected paths: `backend/workbench/http/runs_routes.py`,
  `backend/workbench/report_view_model.py`, `frontend/src/report`,
  `backend/workbench/engine/stages/estimation.py`,
  `backend/workbench/providers`, all Report/data/classification/survey paths,
  and central unrelated Agent/workflow paths
- Dependencies: `v1-8-9-p0-legacy-resume-hardening`,
  `v1-8-9-p0-agent-compiler-core`, `v1-8-9-contract-lock`
- Tests: focused legacy/resume/compiler/workflow suites, the new RED to GREEN
  proposal-binding tests, `PYTHONPATH=backend .venv/bin/python -m compileall
  -q backend/workbench tests`, `git diff --check`, formal verification
- Known gates: browser/provider/full gate/release remain `NOT VERIFIED`;
  commit is local only and push/PR/merge/tag remain approval-gated

## Boundary
- Affected paths: `backend/workbench/http/agent_routes.py`, `backend/workbench/agent/orchestrator.py`, `backend/workbench/agent/proposals.py`, `backend/workbench/contracts/agent/planning.py`, `tests/test_v189_legacy_route_authority.py`
- Allowed paths: `backend/workbench/http/agent_routes.py`, `backend/workbench/agent/orchestrator.py`, `backend/workbench/agent/proposals.py`, `backend/workbench/contracts/agent/planning.py`, `tests/test_v189_legacy_route_authority.py`
- Protected paths: `backend/workbench/http/runs_routes.py`, `backend/workbench/report_view_model.py`, `frontend/src/report`, `backend/workbench/engine/stages/estimation.py`, `backend/workbench/providers`
- Dependencies: `v1-8-9-p0-legacy-resume-hardening`, `v1-8-9-p0-agent-compiler-core`, `v1-8-9-contract-lock`
- Tests: `PYTHONPATH=backend .venv/bin/python -m pytest tests/test_v189_legacy_route_authority.py tests/test_v189_legacy_proposal_binding.py tests/test_v189_resume_authority.py tests/test_v189_workflow_truth.py tests/test_workflow_resume.py tests/test_workflow_runtime.py -q`, `PYTHONPATH=backend .venv/bin/python -m compileall -q backend/workbench tests`, `git diff --check`
- Known gates: `browser/provider/full gate/release remain NOT VERIFIED`, `push/PR/merge/tag require explicit approval`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
### v1-8-8-statistical-truth-cleanup (2026-08-13T10:11:25.000Z)

Completed formal devline v1-8-8-statistical-truth-cleanup; final_state=COMPLETED; failure_lesson_keys=none

### v1-8-4-agent-evidence-loop (2026-07-28T15:52:01.000Z)

Completed formal devline v1-8-4-agent-evidence-loop; final_state=COMPLETED; failure_lesson_keys=agent-completed-operation-evidence-boundary, public-artifact-aggregate-budget

### v1-8-8-p7-agent-adoption (2026-08-09T03:20:32.000Z)

Completed formal devline v1-8-8-p7-agent-adoption; final_state=COMPLETED; failure_lesson_keys=browser-report-remains-not-verified, declaration-derived-option-boundaries, design-diagnostic-neutral-envelope, generated-tool-schema-runtime-validation, p7-artifact-identity-preserves-repeatability, parent-workflow-owns-child-vocabulary, workflow-errors-preserve-step-cause

### v1-8-4-agent-model-composition (2026-07-31T02:50:00.000Z)

Completed formal devline v1-8-4-agent-model-composition; final_state=COMPLETED; failure_lesson_keys=action-mode-route-enforcement, agent-covariance-interpretation-guardrail, agent-provider-and-tool-boundaries, bounded-model-specification-evidence, bounded-node-evidence-visibility, browser-blocked-run-lineage-identity, browser-policy-blocked-ui-acceptance, canonical-terminal-inspection-reuse, checkpoint-host-gate-separation, closing-event-timestamp-must-follow-the-incident, coefficient-batch-limit-protocol, covariance-comparison-interpretation-boundary, declared-white-test-post-estimation, derive-workflow-artifacts-server-side, existing-genesis-route-tests-failed, failed-inspection-retry, fms-event-enums-must-match-contract, fms-event-input-must-be-repository-relative, formal-event-redaction-text-ambiguity, formal-event-requires-real-evidence-digest, genesis-draft-url-visibility, genesis-draft-visibility-regression, global-agent-model-figure-evidence, global-agent-numeric-evidence-transcription, global-agent-workflow-answer-path, historical-proposal-terminal-message, inherited-suite-failures-must-be-baselined, notebook-persisted-lifecycle, notebook-planner-must-recover-to-server-pinned-rerun-target, notebook-planner-proposes-rerun-outside-active-head-lineage, notebook-planning-deadline-must-be-explicit-and-user-aligned, notebook-planning-evidence-admission, notebook-planning-exceeds-visible-timeout-without-terminal-state, notebook-workflow-dependency-shape-correction, notebook-workflow-evidence-bridge, panel-workflow-model-composition, persisted-draft-hydration-before-empty, planning-elapsed-counter-resets-on-remount, post-estimation-must-reproduce-declared-covariance, post-estimation-requires-explicit-step, predictor-residual-diagnostic-evidence, preexisting-backend-suite-failures, progress-clock-anchors-to-attempt, proposal-ready-boundary-updates-call-count, proposal-ready-terminal-state, provider-catalog-expectation-mismatch, provider-catalog-test-alignment, real-run-tests-must-claim-a-clean-slot, rescope-leaf-path-depth, separate-existing-route-failure, structured-evidence-not-prose-token, verified-categorical-indicator-reuse, white-test-auxiliary-rank-stability, white-test-own-rank-policy, workflow-branch-covariance-preservation, workflow-pin-registry-artifact-identity

### v1-8-3-integration-acceptance (2026-07-28T12:11:00.000Z)

Completed formal devline v1-8-3-integration-acceptance; final_state=COMPLETED; failure_lesson_keys=formal-cli-command-surface, formal-scope-narrowing, supported-host-containment-required

### v1-8-3-mem3-memory-curator-exact-baseline (2026-07-27T11:35:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator-exact-baseline; final_state=COMPLETED; failure_lesson_keys=curator-contract-first, review-api-awaits-response

### v1-8-3-mem3-memory-curator (2026-07-27T11:10:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator; final_state=CLOSED; failure_lesson_keys=none

### v1-8-3-cf2-dependency-bundles (2026-07-26T14:13:57.917Z)

Completed formal devline v1-8-3-cf2-dependency-bundles; final_state=COMPLETED; failure_lesson_keys=none

### v1-8-9-p0-agent-compiler-remediation-4 (2026-08-16T13:45:00.000Z)

Completed formal devline v1-8-9-p0-agent-compiler-remediation-4; final_state=COMPLETED; failure_lesson_keys=compiler-proof-copy-must-fail-closed, compiler-remediation4-host-authority-and-fd-reservation, compiler-remediation4-red-tests-before-fix

### v1-8-9-p0-agent-compiler-remediation-3 (2026-08-16T12:20:00.000Z)

Completed formal devline v1-8-9-p0-agent-compiler-remediation-3; final_state=COMPLETED; failure_lesson_keys=compiler-bootstrap-proof, compiler-durable-reservation, compiler-public-durable-store, compiler-sealed-scope-authority, compiler-selection-admission, discovery-server-scope-binding, legacy-c0-issuer-dependency
