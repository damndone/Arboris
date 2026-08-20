# Frozen Context Pack

Line: `v1-8-9-p0-legacy-resume-remediation-3`
Baseline SHA: `d545e9a08d8e3065e482db32852d873710d10edd`

## Objective
# Workbench v1.8.9 P0 Legacy/Resume Remediation-3 Objective

Close the remaining NOT COMPLIANT findings against remediation-2 tip
`d545e9a08d8e3065e482db32852d873710d10edd`. This line is independent of and
must not rewrite `v1-8-9-p0-legacy-resume-remediation-2` or any other formal
line, root checkout, or worktree.

Required outcomes:

- A ProposalStore proposal without a complete server-owned `server_compilation`
  record fails closed. The record must contain actor, session, project,
  semantic-plan hash, target, chain, operation, compilation record, and
  confirmation identity. The persisted proposal target, chain, operation, and
  every scope/identity field must exactly match the server compilation record;
  generic incomplete proposals and cross-scope proposals never enter a
  compiler binding.
- The legacy route's `_proposal_for_session` or one equivalent route-owned
  boundary must reread the persisted proposal, recompute the canonical
  ProposalStore fingerprint from persisted fields, and reject any tampered
  target or other critical field before `_cutover_authority`, compiler
  `record`, `execute`, claim, or write. A stale original fingerprint cannot
  authorize mutated persisted content.
- Repository/route probes use real ProposalStore files and the route-owned
  authority store to cover incomplete compilation, cross-scope identity,
  persisted target tamper with the old fingerprint retained, forged caller
  revision, forged receipt, and replay. Each rejection is fail closed with no
  authority/record/execute/claim/write side effect.
- Existing Resume completion, artifact, output, lineage, and model-branch
  validation remains protected by the existing focused suites, including the
  terminal model-step adversarial path.
- Formal evidence records this line's exact baseline, RED failures, review/
  gap findings, GREEN results, exact implementation commit, and formal
  manifest. No previous `355 passed` or other historical metric is reused as
  this line's result.

## Boundary

- Affected paths: `backend/workbench/agent/orchestrator.py`,
  `backend/workbench/http/agent_routes.py`,
  `tests/test_v189_legacy_resume_remediation3.py`,
  `docs/superpowers/objectives/2026-08-20-v1.8.9-p0-legacy-resume-remediation-3-objective.md`,
  `docs/superpowers/plans/2026-08-20-v1.8.9-p0-legacy-resume-remediation-3.md`
- Allowed paths: exactly the affected paths above
- Protected paths: `backend/workbench/http/runs_routes.py`,
  `backend/workbench/report_view_model.py`, `frontend/src/report`,
  `backend/workbench/engine/stages/estimation.py`,
  `backend/workbench/providers`, all Report/data/classification/survey paths,
  root-level files, all other worktrees, and all prior `.agent/devlines/*`
  records including remediation-2
- Baseline: `d545e9a08d8e3065e482db32852d873710d10edd`
- Dependencies: `v1-8-9-p0-legacy-resume-remediation-2`,
  `v1-8-9-p0-legacy-proposal-binding-remediation`,
  `v1-8-9-p0-legacy-resume-hardening`, `v1-8-9-p0-agent-compiler-core`,
  `v1-8-9-contract-lock`
- Tests: RED repository/route probes for incomplete/cross-scope/tampered
  persisted proposals, forged caller revision/receipt, and replay; GREEN
  legacy route/proposal/compiler/resume/workflow/Agent-notebook focused suites;
  isolated compileall; `git diff --check`; formal verify; formal retrospective
- Known gates: browser acceptance NOT VERIFIED, provider/external runtime NOT
  VERIFIED, full repository gate NOT VERIFIED, release NOT VERIFIED,
  merge/tag NOT VERIFIED; no dependency install, root write, push, PR, merge,
  tag, or release operation

## Boundary
- Affected paths: `backend/workbench/agent/orchestrator.py`, `backend/workbench/http/agent_routes.py`, `tests/test_v189_legacy_resume_remediation3.py`, `tests/test_v189_agent_notebook_cutover.py`, `tests/test_v189_legacy_resume_remediation2.py`, `docs/superpowers/objectives/2026-08-20-v1.8.9-p0-legacy-resume-remediation-3-objective.md`, `docs/superpowers/plans/2026-08-20-v1.8.9-p0-legacy-resume-remediation-3.md`
- Allowed paths: `backend/workbench/agent/orchestrator.py`, `backend/workbench/http/agent_routes.py`, `tests/test_v189_legacy_resume_remediation3.py`, `tests/test_v189_agent_notebook_cutover.py`, `tests/test_v189_legacy_resume_remediation2.py`, `docs/superpowers/objectives/2026-08-20-v1.8.9-p0-legacy-resume-remediation-3-objective.md`, `docs/superpowers/plans/2026-08-20-v1.8.9-p0-legacy-resume-remediation-3.md`
- Protected paths: `backend/workbench/http/runs_routes.py`, `backend/workbench/report_view_model.py`, `frontend/src/report`, `backend/workbench/engine/stages/estimation.py`, `backend/workbench/providers`, `Report`, `data`, `classification`, `survey`, `root-level-files`, `.agent/devlines/v1-8-9-p0-legacy-resume-remediation-2`, `other-worktrees`
- Dependencies: `v1-8-9-p0-legacy-resume-remediation-2`, `v1-8-9-p0-legacy-proposal-binding-remediation`, `v1-8-9-p0-legacy-resume-hardening`, `v1-8-9-p0-agent-compiler-core`, `v1-8-9-contract-lock`
- Tests: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend .venv/bin/python -m pytest tests/test_v189_legacy_resume_remediation3.py -q`, `focused legacy route/proposal/compiler/resume/workflow/agent-notebook suites including remediation-3`, `isolated compileall with PYTHONPYCACHEPREFIX under /private/tmp`, `git diff --check`, `formal verify and retrospective`
- Known gates: `browser acceptance NOT VERIFIED`, `provider/external runtime NOT VERIFIED`, `full repository gate NOT VERIFIED`, `release NOT VERIFIED`, `merge/tag NOT VERIFIED`, `no dependency installation, root write, push, PR, merge, tag, or release operation`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
### v1-8-4-agent-evidence-loop (2026-07-28T15:52:01.000Z)

Completed formal devline v1-8-4-agent-evidence-loop; final_state=COMPLETED; failure_lesson_keys=agent-completed-operation-evidence-boundary, public-artifact-aggregate-budget

### v1-8-8-statistical-truth-cleanup (2026-08-13T10:11:25.000Z)

Completed formal devline v1-8-8-statistical-truth-cleanup; final_state=COMPLETED; failure_lesson_keys=none

### v1-8-8-p7-agent-adoption (2026-08-09T03:20:32.000Z)

Completed formal devline v1-8-8-p7-agent-adoption; final_state=COMPLETED; failure_lesson_keys=browser-report-remains-not-verified, declaration-derived-option-boundaries, design-diagnostic-neutral-envelope, generated-tool-schema-runtime-validation, p7-artifact-identity-preserves-repeatability, parent-workflow-owns-child-vocabulary, workflow-errors-preserve-step-cause

### v1-8-4-agent-model-composition (2026-07-31T02:50:00.000Z)

Completed formal devline v1-8-4-agent-model-composition; final_state=COMPLETED; failure_lesson_keys=action-mode-route-enforcement, agent-covariance-interpretation-guardrail, agent-provider-and-tool-boundaries, bounded-model-specification-evidence, bounded-node-evidence-visibility, browser-blocked-run-lineage-identity, browser-policy-blocked-ui-acceptance, canonical-terminal-inspection-reuse, checkpoint-host-gate-separation, closing-event-timestamp-must-follow-the-incident, coefficient-batch-limit-protocol, covariance-comparison-interpretation-boundary, declared-white-test-post-estimation, derive-workflow-artifacts-server-side, existing-genesis-route-tests-failed, failed-inspection-retry, fms-event-enums-must-match-contract, fms-event-input-must-be-repository-relative, formal-event-redaction-text-ambiguity, formal-event-requires-real-evidence-digest, genesis-draft-url-visibility, genesis-draft-visibility-regression, global-agent-model-figure-evidence, global-agent-numeric-evidence-transcription, global-agent-workflow-answer-path, historical-proposal-terminal-message, inherited-suite-failures-must-be-baselined, notebook-persisted-lifecycle, notebook-planner-must-recover-to-server-pinned-rerun-target, notebook-planner-proposes-rerun-outside-active-head-lineage, notebook-planning-deadline-must-be-explicit-and-user-aligned, notebook-planning-evidence-admission, notebook-planning-exceeds-visible-timeout-without-terminal-state, notebook-workflow-dependency-shape-correction, notebook-workflow-evidence-bridge, panel-workflow-model-composition, persisted-draft-hydration-before-empty, planning-elapsed-counter-resets-on-remount, post-estimation-must-reproduce-declared-covariance, post-estimation-requires-explicit-step, predictor-residual-diagnostic-evidence, preexisting-backend-suite-failures, progress-clock-anchors-to-attempt, proposal-ready-boundary-updates-call-count, proposal-ready-terminal-state, provider-catalog-expectation-mismatch, provider-catalog-test-alignment, real-run-tests-must-claim-a-clean-slot, rescope-leaf-path-depth, separate-existing-route-failure, structured-evidence-not-prose-token, verified-categorical-indicator-reuse, white-test-auxiliary-rank-stability, white-test-own-rank-policy, workflow-branch-covariance-preservation, workflow-pin-registry-artifact-identity

### v1-8-3-cf2-dependency-bundles (2026-07-26T14:13:57.917Z)

Completed formal devline v1-8-3-cf2-dependency-bundles; final_state=COMPLETED; failure_lesson_keys=none

### v1-8-4-reopened-incident-truth (2026-07-31T08:10:00.000Z)

Completed formal devline v1-8-4-reopened-incident-truth; final_state=COMPLETED; failure_lesson_keys=full-gate-requires-non-nested-seatbelt, gate-requires-non-nested-sandbox

### v1-8-3-integration-acceptance (2026-07-28T12:11:00.000Z)

Completed formal devline v1-8-3-integration-acceptance; final_state=COMPLETED; failure_lesson_keys=formal-cli-command-surface, formal-scope-narrowing, supported-host-containment-required

### v1-8-3-mem3-memory-curator-exact-baseline (2026-07-27T11:35:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator-exact-baseline; final_state=COMPLETED; failure_lesson_keys=curator-contract-first, review-api-awaits-response

### v1-8-3-mem3-memory-curator (2026-07-27T11:10:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator; final_state=CLOSED; failure_lesson_keys=none

### v1-8-3-document-authority-consolidation (2026-07-26T03:30:00.000Z)

Completed formal devline v1-8-3-document-authority-consolidation; final_state=COMPLETED; failure_lesson_keys=none
