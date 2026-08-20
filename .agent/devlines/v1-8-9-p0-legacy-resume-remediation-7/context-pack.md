# Frozen Context Pack

Line: `v1-8-9-p0-legacy-resume-remediation-7`
Baseline SHA: `4764a97b2093940417eeb9303d06aacc086ff82c`

## Objective
# Workbench v1.8.9 P0 Legacy/Resume Remediation-7 Objective

## Objective

Close the P0 authority bypass found at baseline `4764a97b2093940417eeb9303d06aacc086ff82c`:
caller-created `ProposalStoreCapabilityIssuerV1` objects must not be able to
self-register mutation admission or service-entry admission and then mint a
proposal-store capability that reaches `WorkbenchOrchestrator.decline_proposal`
side effects.

## Required outcomes

- Make issuer and service admission server-owned opaque authority. A caller may
  consume only an already issued, non-forgeable service-entry handle; it cannot
  register or upgrade an issuer.
- Bind every issuer and capability to the existing registry, server secret,
  owner identity, nonce, process generation, PID, and exact store-root identity
  boundaries. Copying, serialization, reconstruction, and cross-process use
  must fail closed.
- Keep the formal compiler, route, and workflow proposal paths valid.
- Add adversarial TDD regressions for caller-created issuer plus self-registered
  service handle, and imported/default route issuer directly registered then
  minted. Both must reject before proposal, repository, or event side effects.
- Run focused legacy/resume/route/compiler/workflow suites, the adversarial
  suite, compileall, and diff-check.
- Record the historical `tests/test_agent_proposal_operations.py` 19 direct-
  service failures as a known GAP; do not weaken the authority boundary.

## Boundary

Affected paths:

- `backend/workbench/agent/proposals.py`
- `backend/workbench/agent/orchestrator.py`
- `tests/test_v189_legacy_resume_remediation7.py`
- `docs/superpowers/objectives/2026-08-20-v1.8.9-p0-legacy-resume-remediation-7-objective.md`
- `docs/superpowers/plans/2026-08-20-v1.8.9-p0-legacy-resume-remediation-7.md`
- `docs/superpowers/handoff/2026-08-20-v1.8.9-p0-legacy-resume-remediation-7-handoff.md`

Allowed paths are exactly the affected paths above. Protected paths include
the root checkout, all other worktrees, all predecessor `.agent/devlines/*`
records, Report/data/classification/survey/provider paths, unrelated HTTP
routes, and predecessor remediation source/test files unless a regression
proves a narrowly necessary compatibility edit.

Baseline: `4764a97b2093940417eeb9303d06aacc086ff82c`.

Dependencies: legacy/resume remediation-6 and its predecessor authority
hardening lines, Agent compiler cutover, route authority, workflow truth, and
contract-lock evidence. Historical closeout counts are inputs only, not this
line's evidence.

## Tests and gates

- RED then GREEN: `tests/test_v189_legacy_resume_remediation7.py`.
- Focused legacy/resume/route/compiler/workflow suites and the historical
  direct-service suite, with its 19 failures recorded as a known GAP if still
  present.
- `PYTHONPATH=backend .venv/bin/python -m compileall -q backend/workbench tests`.
- `git diff --check`.
- Formal line verify, final GATE, retrospective, and exact HEAD/digest handoff.

Known external gates remain outside this line: browser acceptance, external
provider runtime, host restart, true multi-worker deployment, full repository
gate, integration/release/merge/tag. They remain `NOT VERIFIED` unless directly
run and evidenced here. No dependency installation, root write, other-worktree
write, push, merge, tag, or release operation is authorized.

## Boundary
- Affected paths: `backend/workbench/agent/proposals.py`, `backend/workbench/agent/orchestrator.py`, `tests/test_v189_legacy_resume_remediation7.py`, `docs/superpowers/objectives/2026-08-20-v1.8.9-p0-legacy-resume-remediation-7-objective.md`, `docs/superpowers/plans/2026-08-20-v1.8.9-p0-legacy-resume-remediation-7.md`, `docs/superpowers/handoff/2026-08-20-v1.8.9-p0-legacy-resume-remediation-7-handoff.md`
- Allowed paths: `backend/workbench/agent/proposals.py`, `backend/workbench/agent/orchestrator.py`, `tests/test_v189_legacy_resume_remediation7.py`, `docs/superpowers/objectives/2026-08-20-v1.8.9-p0-legacy-resume-remediation-7-objective.md`, `docs/superpowers/plans/2026-08-20-v1.8.9-p0-legacy-resume-remediation-7.md`, `docs/superpowers/handoff/2026-08-20-v1.8.9-p0-legacy-resume-remediation-7-handoff.md`
- Protected paths: `root-checkout`, `other-worktrees`, `predecessor-formal-lines`, `Report`, `data`, `classification`, `survey`, `providers`
- Dependencies: none
- Tests: `PYTHONPATH=backend .venv/bin/python -m pytest tests/test_v189_legacy_resume_remediation7.py -q --disable-warnings --maxfail=1`, `PYTHONPATH=backend .venv/bin/python -m pytest tests/test_v189_legacy_resume_remediation6.py tests/test_v189_legacy_resume_remediation5.py tests/test_v189_legacy_resume_remediation2.py -q --disable-warnings --maxfail=1`, `PYTHONPATH=backend .venv/bin/python -m pytest tests/test_v189_legacy_route_authority.py tests/test_v189_agent_notebook_cutover.py tests/test_workflow_resume.py tests/test_workflow_seam.py -q --disable-warnings --maxfail=1`, `PYTHONPATH=backend .venv/bin/python -m pytest tests/test_agent_proposal_operations.py -q --disable-warnings`, `PYTHONPATH=backend .venv/bin/python -m compileall -q backend/workbench tests`, `git diff --check`
- Known gates: `historical direct-service suite may retain exactly 19 failures; record as known GAP and do not relax security boundary`, `browser acceptance, external provider runtime, host restart, multi-worker deployment, full repository gate, integration, release, merge, and tag remain NOT VERIFIED`

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

### v1-8-3-b0-authority-verifier-redesign (2026-07-26T09:04:34.000Z)

Completed formal devline v1-8-3-b0-authority-verifier-redesign; final_state=COMPLETED; failure_lesson_keys=none

### v1-8-3-document-authority-consolidation (2026-07-26T03:30:00.000Z)

Completed formal devline v1-8-3-document-authority-consolidation; final_state=COMPLETED; failure_lesson_keys=none
