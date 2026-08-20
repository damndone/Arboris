# Frozen Context Pack

Line: `v1-8-9-p0-legacy-resume-remediation-5`
Baseline SHA: `137cc227e6819047c1124d40dbcce0d4255273cf`

## Objective
# Workbench v1.8.9 P0 Legacy/Resume Remediation-5 Objective

Remediate the independent spec-review finding against exact remediation-4 tip
`137cc227e6819047c1124d40dbcce0d4255273cf` without editing remediation-4,
any predecessor formal line, the root checkout, or another worktree.

## Required outcomes

- `WorkbenchOrchestrator` must not construct or expose a usable raw
  `ProposalStore` for a direct caller. Proposal mutation requires an opaque,
  server-owned `ProposalStoreCapabilityV1` admitted for the current repository
  scope; a raw, caller-created, temporary, reconstructed, cross-scope, or
  tampered store fails closed before any persistence or transcript write.
- `revise_proposal()` and `decline_proposal()` reject the default/direct
  service path with a typed boundary error before disk or memory mutation.
  Explicit server-route use is retained only when the route passes its
  server-owned capability and the capability root matches the repository.
- Agent proposal routes pass the same server-owned capability into the
  orchestrator for legitimate create/revise/decline flows. Legacy confirmation
  and Resume artifact/output/lineage/model-branch protections remain intact.
- Real probes cover direct revise, direct decline, default-store exposure,
  raw/temporary/reconstructed/cross-scope/tampered store rejection, replay
  rejection, route success, Resume regression, and zero disk/memory side
  effects on every rejected path.
- Formal evidence records exact reproducible nodeids/counts and current tip;
  no historical `448 passed` claim is reused without its complete command.

## Boundary

- Affected paths: `backend/workbench/agent/orchestrator.py`,
  `backend/workbench/http/agent_routes.py`,
  `tests/test_v189_legacy_resume_remediation5.py`,
  `tests/test_v189_legacy_route_authority.py`,
  `tests/test_v189_agent_notebook_cutover.py`,
  `tests/test_v189_resume_authority.py`,
  `tests/test_workflow_resume.py`,
  `docs/superpowers/objectives/2026-08-20-v1.8.9-p0-legacy-resume-remediation-5-objective.md`,
  `docs/superpowers/plans/2026-08-20-v1.8.9-p0-legacy-resume-remediation-5.md`
- Allowed paths: exactly the affected paths above.
- Protected paths: root-level files, all other worktrees, all predecessor
  `.agent/devlines/*` records, `Report`, `data`, `classification`, `survey`,
  `backend/workbench/providers`, `backend/workbench/http/runs_routes.py`,
  `backend/workbench/report_view_model.py`, and
  `backend/workbench/engine/stages/estimation.py`.
- Baseline: `137cc227e6819047c1124d40dbcce0d4255273cf`.
- Dependencies: remediation-4, remediation-3, remediation-2,
  legacy-proposal-binding, legacy/resume hardening, Agent compiler core, and
  contract-lock formal evidence.
- Tests: RED direct revise/decline/default-store and no-side-effect probes;
  GREEN exact remediation-5 nodeids plus legacy route, Agent-Notebook,
  Resume, and workflow focused suites; isolated compileall; `git diff --check`;
  formal verify and retrospective.
- Known gates: browser acceptance NOT VERIFIED; real provider/external runtime
  NOT VERIFIED; host restart NOT VERIFIED; multi-worker/concurrency NOT
  VERIFIED; full repository gate NOT VERIFIED; release NOT VERIFIED;
  merge/tag NOT VERIFIED. No dependency installation, root write, push, PR,
  merge, tag, or release operation.

## Boundary
- Affected paths: `backend/workbench/agent/orchestrator.py`, `backend/workbench/http/agent_routes.py`, `tests/test_v189_legacy_resume_remediation5.py`, `tests/test_v189_legacy_route_authority.py`, `tests/test_v189_agent_notebook_cutover.py`, `tests/test_v189_resume_authority.py`, `tests/test_workflow_resume.py`, `tests/test_v189_legacy_resume_remediation2.py`, `docs/superpowers/objectives/2026-08-20-v1.8.9-p0-legacy-resume-remediation-5-objective.md`, `docs/superpowers/plans/2026-08-20-v1.8.9-p0-legacy-resume-remediation-5.md`, `docs/superpowers/handoff/2026-08-20-v1.8.9-p0-legacy-resume-remediation-5-handoff.md`
- Allowed paths: `backend/workbench/agent/orchestrator.py`, `backend/workbench/http/agent_routes.py`, `tests/test_v189_legacy_resume_remediation5.py`, `tests/test_v189_legacy_route_authority.py`, `tests/test_v189_agent_notebook_cutover.py`, `tests/test_v189_resume_authority.py`, `tests/test_workflow_resume.py`, `tests/test_v189_legacy_resume_remediation2.py`, `docs/superpowers/objectives/2026-08-20-v1.8.9-p0-legacy-resume-remediation-5-objective.md`, `docs/superpowers/plans/2026-08-20-v1.8.9-p0-legacy-resume-remediation-5.md`, `docs/superpowers/handoff/2026-08-20-v1.8.9-p0-legacy-resume-remediation-5-handoff.md`
- Protected paths: `Report`, `data`, `classification`, `survey`, `backend/workbench/providers`, `backend/workbench/http/runs_routes.py`, `backend/workbench/report_view_model.py`, `backend/workbench/engine/stages/estimation.py`, `root-level-files`, `other-worktrees`, `.agent/devlines/v1-8-9-p0-legacy-resume-remediation-4`, `.agent/devlines/v1-8-9-p0-legacy-resume-remediation-3`, `.agent/devlines/v1-8-9-p0-legacy-resume-remediation-2`
- Dependencies: `v1-8-9-p0-legacy-resume-remediation-4`, `v1-8-9-p0-legacy-resume-remediation-3`, `v1-8-9-p0-legacy-resume-remediation-2`, `v1-8-9-p0-legacy-proposal-binding-remediation`, `v1-8-9-p0-legacy-resume-hardening`, `v1-8-9-p0-agent-compiler-core`, `v1-8-9-contract-lock`
- Tests: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend .venv/bin/python -m pytest tests/test_v189_legacy_resume_remediation5.py -q`, `exact legacy route/ProposalStore/compiler/Agent-Notebook/Resume/workflow focused pytest command with nodeids`, `isolated compileall with disposable PYTHONPYCACHEPREFIX and zero remaining bytecode`, `git diff --check`, `formal verify and retrospective`
- Known gates: `browser acceptance NOT VERIFIED`, `real provider/external runtime NOT VERIFIED`, `host restart NOT VERIFIED`, `multi-worker/concurrency NOT VERIFIED`, `full repository gate NOT VERIFIED`, `release NOT VERIFIED`, `merge/tag NOT VERIFIED`, `no dependency installation, root write, push, PR, merge, tag, or release operation`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
### v1-8-4-agent-evidence-loop (2026-07-28T15:52:01.000Z)

Completed formal devline v1-8-4-agent-evidence-loop; final_state=COMPLETED; failure_lesson_keys=agent-completed-operation-evidence-boundary, public-artifact-aggregate-budget

### v1-8-8-statistical-truth-cleanup (2026-08-13T10:11:25.000Z)

Completed formal devline v1-8-8-statistical-truth-cleanup; final_state=COMPLETED; failure_lesson_keys=none

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
