# Frozen Context Pack

Line: `v1-8-9-p0-workflow-truth-remediation-5`
Baseline SHA: `c9f3c4ed3e07faf6f57f795a5e35fa6f8042c749`

## Objective
# v1.8.9 P0 Workflow Truth Remediation 5 Objective

Close the remaining Workflow Truth trust and containment gaps found by the
remediation-4 independent review. A caller-created workflow endpoint or
directory FD must not be accepted as host authority. Completion must prove
that every artifact is registered by the admitted target run and branch, not
merely match caller-supplied metadata, hashes or a public registry row. All
formal report/export writers must use the same admitted receipt and must
validate the destination before writing so symlinks cannot cause an outside
file to be created before failure.

Baseline: Contract Lock C0 c9f3c4ed3e07faf6f57f795a5e35fa6f8042c749
Remediation line: v1-8-9-p0-workflow-truth-remediation-5
Worktree: /Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.9-p0-workflow-truth

Required outcomes:

- workflow host/evidence authority is accepted only from the deployment-owned
  supervisor boundary; caller-created path/FD/socket/config and self-authored
  authority fail closed before any formal write;
- completion verifies durable artifact provenance, exact run/branch ownership,
  source model-run identity, expected output and digest against an admitted
  server-side registry/receipt, rejecting foreign-run and forged same-run
  registry/artifact cases;
- public HTML/PDF/XLSX/report/export writers are receipt-gated before any IO;
  destination directories and all parent components are checked before write,
  and symlink/path replacement cannot leave outside artifacts behind;
- existing receipt, post-estimation, restart, FD/inode and no-write behavior
  remains intact;
- production host resolver and Agent/Notebook cutover remain explicit
  integration dependencies and are not claimed verified by local fixtures.

## Boundary
- Affected paths: `backend/workbench/agent/workflow.py`, `backend/workbench/agent/workflow_runtime.py`, `backend/workbench/reporting.py`, `backend/workbench/exports.py`, `backend/workbench/providers/builtin/workflow_post_estimation.json`, `tests/test_v189_workflow_truth.py`, `tests/test_workflow_resume.py`, `tests/test_workflow_runtime.py`, `tests/test_reporting.py`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-p0-workflow-truth-remediation-5.md`, `docs/superpowers/handoff/2026-08-16-v1.8.9-p0-workflow-truth-remediation-5-handoff.md`
- Allowed paths: `backend/workbench/agent/workflow.py`, `backend/workbench/agent/workflow_runtime.py`, `backend/workbench/reporting.py`, `backend/workbench/exports.py`, `backend/workbench/providers/builtin/workflow_post_estimation.json`, `tests/test_v189_workflow_truth.py`, `tests/test_workflow_resume.py`, `tests/test_workflow_runtime.py`, `tests/test_reporting.py`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-p0-workflow-truth-remediation-5.md`, `docs/superpowers/handoff/2026-08-16-v1.8.9-p0-workflow-truth-remediation-5-handoff.md`
- Protected paths: `backend/workbench/contracts`, `backend/workbench/evidence`, `backend/workbench/services/results_service.py`, `backend/workbench/report_view_model.py`, `backend/workbench/predictive_research`, `frontend`, `scripts/gate.sh`, `.agent/devlines`
- Dependencies: `v1-8-9-p0-workflow-truth-remediation-4`
- Tests: `cd backend && PYTHONPATH=$PWD ../.venv/bin/python -m pytest ../tests/test_v189_workflow_truth.py ../tests/test_workflow_resume.py ../tests/test_workflow_runtime.py ../tests/test_reporting.py -q`
- Known gates: `production host resolver, shared Agent/Notebook cutover, provider execution, browser, full gate and release remain NOT VERIFIED`, `no commit, merge, push or tag is authorized`

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

### v1-8-4-reopened-incident-truth (2026-07-31T08:10:00.000Z)

Completed formal devline v1-8-4-reopened-incident-truth; final_state=COMPLETED; failure_lesson_keys=full-gate-requires-non-nested-seatbelt, gate-requires-non-nested-sandbox

### v1-8-4-open-incidents-remediation (2026-07-31T04:08:00.000Z)

Completed formal devline v1-8-4-open-incidents-remediation; final_state=COMPLETED; failure_lesson_keys=closing-evidence-must-postdate-the-work

### v1-8-4-model-term-reuse (2026-07-31T02:50:00.000Z)

Completed formal devline v1-8-4-model-term-reuse; final_state=COMPLETED; failure_lesson_keys=none
