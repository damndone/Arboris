# Frozen Context Pack

Line: `v1-8-9-p0-legacy-resume-remediation-4`
Baseline SHA: `8003f27b95bf8f8f2dcad4c35f556d68238c079e`

## Objective
# Workbench v1.8.9 P0 Legacy/Resume Remediation-4 Objective

Remediate the independent spec-review finding against exact remediation-3 tip
`8003f27b95bf8f8f2dcad4c35f556d68238c079e` without editing remediation-3 or
any other formal line, root checkout, or worktree.

## Required outcomes

- ProposalStore admission is an opaque, server-issued capability rather than a
  `type(ProposalStore)` check. A caller-created, temporary, forged, copied, or
  reconstructed store is rejected even when it points at a complete file. The
  compiler binds only a capability admitted by its server authority, and the
  persisted compilation record and confirmation identity come from that same
  authority and exactly match proposal id, revision, fingerprint, semantic
  plan hash, actor, session, project, target, chain, and operation.
- The legacy route reloads a canonical persisted proposal through the
  server-owned store capability before parsing any precondition or consulting
  authority, record, execute, claim, or write state. `SimpleNamespace`, a
  synthetic/reconstructed ProposalRevision, forged caller revision, stale
  receipt, replay, and persisted tamper all fail closed with no side effect.
- Real repository and route probes cover caller-store admission, incomplete and
  cross-scope compilation, persisted target tamper with an old fingerprint,
  forged revision/receipt/replay, and synthetic direct-service calls. Positive
  paths use the server-owned persisted proposal lifecycle.
- Existing Resume artifact/output/lineage/model-branch and Agent/Notebook
  focused safety coverage remains green. The remediation-3 `COMPLETED` versus
  `unresolved=5` contradiction is recorded as a new formal review/gap and
  resolved by this line's exact evidence; historical counts are not reused.

## Boundary

- Affected paths: `backend/workbench/agent/proposals.py`,
  `backend/workbench/agent/orchestrator.py`,
  `backend/workbench/http/agent_routes.py`,
  `tests/test_v189_legacy_resume_remediation4.py`,
  `tests/test_v189_legacy_resume_remediation3.py`,
  `tests/test_v189_legacy_resume_remediation2.py`,
  `tests/test_v189_agent_notebook_cutover.py`,
  `tests/test_v189_legacy_route_authority.py`,
  `docs/superpowers/objectives/2026-08-19-v1.8.9-p0-legacy-resume-remediation-4-objective.md`,
  `docs/superpowers/plans/2026-08-19-v1.8.9-p0-legacy-resume-remediation-4.md`
- Allowed paths: exactly the affected paths above.
- Protected paths: all root-level files, all other worktrees, all prior
  `.agent/devlines/*` records, `Report`, `data`, `classification`, `survey`,
  `backend/workbench/providers`, `backend/workbench/http/runs_routes.py`,
  `backend/workbench/report_view_model.py`, and
  `backend/workbench/engine/stages/estimation.py`.
- Baseline: `8003f27b95bf8f8f2dcad4c35f556d68238c079e`.
- Dependencies: remediation-3 predecessor and its review, remediation-2,
  legacy proposal-binding remediation, legacy/resume hardening, Agent compiler
  core, and contract-lock.
- Tests: RED then GREEN real ProposalStore/compiler/route probes; focused
  legacy route/proposal/compiler/resume/workflow/Agent-Notebook suites;
  isolated compileall with cleanup; `git diff --check`; formal verify and
  retrospective.
- Known gates: browser acceptance NOT VERIFIED; provider/external runtime NOT
  VERIFIED; full repository gate NOT VERIFIED; release NOT VERIFIED;
  merge/tag NOT VERIFIED. No dependency installation, root write, push, PR,
  merge, tag, or release operation.

## Boundary
- Affected paths: `backend/workbench/agent/proposals.py`, `backend/workbench/agent/orchestrator.py`, `backend/workbench/http/agent_routes.py`, `tests/test_v189_legacy_resume_remediation4.py`, `tests/test_v189_legacy_resume_remediation3.py`, `tests/test_v189_legacy_resume_remediation2.py`, `tests/test_v189_agent_notebook_cutover.py`, `tests/test_v189_legacy_route_authority.py`, `docs/superpowers/objectives/2026-08-19-v1.8.9-p0-legacy-resume-remediation-4-objective.md`, `docs/superpowers/plans/2026-08-19-v1.8.9-p0-legacy-resume-remediation-4.md`
- Allowed paths: `backend/workbench/agent/proposals.py`, `backend/workbench/agent/orchestrator.py`, `backend/workbench/http/agent_routes.py`, `tests/test_v189_legacy_resume_remediation4.py`, `tests/test_v189_legacy_resume_remediation3.py`, `tests/test_v189_legacy_resume_remediation2.py`, `tests/test_v189_agent_notebook_cutover.py`, `tests/test_v189_legacy_route_authority.py`, `docs/superpowers/objectives/2026-08-19-v1.8.9-p0-legacy-resume-remediation-4-objective.md`, `docs/superpowers/plans/2026-08-19-v1.8.9-p0-legacy-resume-remediation-4.md`
- Protected paths: `Report`, `data`, `classification`, `survey`, `backend/workbench/providers`, `backend/workbench/http/runs_routes.py`, `backend/workbench/report_view_model.py`, `backend/workbench/engine/stages/estimation.py`, `root-level-files`, `other-worktrees`, `.agent/devlines/v1-8-9-p0-legacy-resume-remediation-3`, `.agent/devlines/v1-8-9-p0-legacy-resume-remediation-2`
- Dependencies: `v1-8-9-p0-legacy-resume-remediation-3`, `v1-8-9-p0-legacy-resume-remediation-2`, `v1-8-9-p0-legacy-proposal-binding-remediation`, `v1-8-9-p0-legacy-resume-hardening`, `v1-8-9-p0-agent-compiler-core`, `v1-8-9-contract-lock`
- Tests: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend .venv/bin/python -m pytest tests/test_v189_legacy_resume_remediation4.py -q`, `focused legacy route/proposal/compiler/resume/workflow/Agent-Notebook pytest suites`, `isolated compileall with a disposable PYTHONPYCACHEPREFIX and zero remaining bytecode`, `git diff --check`, `formal verify and retrospective`
- Known gates: `browser acceptance NOT VERIFIED`, `provider/external runtime NOT VERIFIED`, `full repository gate NOT VERIFIED`, `release NOT VERIFIED`, `merge/tag NOT VERIFIED`, `no dependency installation, root write, push, PR, merge, tag, or release operation`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

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

### v1-8-4-agent-model-composition (2026-07-31T02:50:00.000Z)

Completed formal devline v1-8-4-agent-model-composition; final_state=COMPLETED; failure_lesson_keys=action-mode-route-enforcement, agent-covariance-interpretation-guardrail, agent-provider-and-tool-boundaries, bounded-model-specification-evidence, bounded-node-evidence-visibility, browser-blocked-run-lineage-identity, browser-policy-blocked-ui-acceptance, canonical-terminal-inspection-reuse, checkpoint-host-gate-separation, closing-event-timestamp-must-follow-the-incident, coefficient-batch-limit-protocol, covariance-comparison-interpretation-boundary, declared-white-test-post-estimation, derive-workflow-artifacts-server-side, existing-genesis-route-tests-failed, failed-inspection-retry, fms-event-enums-must-match-contract, fms-event-input-must-be-repository-relative, formal-event-redaction-text-ambiguity, formal-event-requires-real-evidence-digest, genesis-draft-url-visibility, genesis-draft-visibility-regression, global-agent-model-figure-evidence, global-agent-numeric-evidence-transcription, global-agent-workflow-answer-path, historical-proposal-terminal-message, inherited-suite-failures-must-be-baselined, notebook-persisted-lifecycle, notebook-planner-must-recover-to-server-pinned-rerun-target, notebook-planner-proposes-rerun-outside-active-head-lineage, notebook-planning-deadline-must-be-explicit-and-user-aligned, notebook-planning-evidence-admission, notebook-planning-exceeds-visible-timeout-without-terminal-state, notebook-workflow-dependency-shape-correction, notebook-workflow-evidence-bridge, panel-workflow-model-composition, persisted-draft-hydration-before-empty, planning-elapsed-counter-resets-on-remount, post-estimation-must-reproduce-declared-covariance, post-estimation-requires-explicit-step, predictor-residual-diagnostic-evidence, preexisting-backend-suite-failures, progress-clock-anchors-to-attempt, proposal-ready-boundary-updates-call-count, proposal-ready-terminal-state, provider-catalog-expectation-mismatch, provider-catalog-test-alignment, real-run-tests-must-claim-a-clean-slot, rescope-leaf-path-depth, separate-existing-route-failure, structured-evidence-not-prose-token, verified-categorical-indicator-reuse, white-test-auxiliary-rank-stability, white-test-own-rank-policy, workflow-branch-covariance-preservation, workflow-pin-registry-artifact-identity

### v1-8-3-cf2-dependency-bundles (2026-07-26T14:13:57.917Z)

Completed formal devline v1-8-3-cf2-dependency-bundles; final_state=COMPLETED; failure_lesson_keys=none

### v1-8-4-reopened-incident-truth (2026-07-31T08:10:00.000Z)

Completed formal devline v1-8-4-reopened-incident-truth; final_state=COMPLETED; failure_lesson_keys=full-gate-requires-non-nested-seatbelt, gate-requires-non-nested-sandbox

### v1-8-3-document-authority-consolidation (2026-07-26T03:30:00.000Z)

Completed formal devline v1-8-3-document-authority-consolidation; final_state=COMPLETED; failure_lesson_keys=none
