# Frozen Context Pack

Line: `v1-8-9-p0-legacy-resume-remediation-6`
Baseline SHA: `4e8fe623e00a2216f11202fce38527ecfd317e9f`

## Objective
# Workbench v1.8.9 P0 Legacy/Resume Remediation-6 Objective

## Objective

Close the independent spec-review authority bypass remaining at remediation-5
HEAD `4e8fe623e00a2216f11202fce38527ecfd317e9f`. Caller-created,
reconstructed, cross-scope, tampered, replayed, and concurrently misused
proposal-store capabilities must fail closed before proposal, repository, or
event side effects, while the existing route-owned proposal lifecycle remains
valid and compatible.

## Required outcomes

- Replace caller-supplied `owner_token` issuance with a server issuer and
  registry that binds each capability to an issuer identity, nonce, process
  generation, and exact proposal-store root identity.
- Bind the route issuer explicitly into `WorkbenchOrchestrator`; the
  orchestrator must validate the exact issuer/registry binding before every
  proposal read or mutation.
- Direct access to the old `_issue` and `_issue_server_capability` authority
  seams cannot mint a usable capability. Forged, reconstructed, copied,
  serialized, cross-scope, tampered, stale, replayed, and concurrent misuse
  fail closed with zero proposal/repository/event side effects.
- Preserve route-owned create/revise/decline compatibility semantics and the
  existing Resume, legacy compiler, and workflow safety boundaries.
- Add real TDD probes for all rejected classes, side-effect ordering, legal
  route success, one-time/replay behavior, and concurrent misuse.

## Boundary

Affected paths:

- `backend/workbench/agent/proposals.py`
- `backend/workbench/agent/orchestrator.py`
- `backend/workbench/http/agent_routes.py`
- `tests/test_v189_legacy_resume_remediation6.py`
- `docs/superpowers/objectives/2026-08-20-v1.8.9-p0-legacy-resume-remediation-6-objective.md`
- `docs/superpowers/plans/2026-08-20-v1.8.9-p0-legacy-resume-remediation-6.md`
- `docs/superpowers/handoff/2026-08-20-v1.8.9-p0-legacy-resume-remediation-6-handoff.md`

Allowed paths are exactly the affected paths above. Protected paths include
the root checkout, all other worktrees, all predecessor `.agent/devlines/*`
records, Report/data/classification/survey/provider paths, unrelated HTTP
routes, and existing remediation source/test files unless a test regression
proves a narrowly necessary compatibility edit.

Baseline: `4e8fe623e00a2216f11202fce38527ecfd317e9f`.

Dependencies: remediation-5, remediation-4, remediation-3, remediation-2,
legacy proposal-binding remediation, legacy/resume authority hardening, Agent
compiler core, and contract-lock evidence. These are historical inputs only;
their closeout counts are not evidence for this line.

## Tests and gates

- RED then GREEN: `tests/test_v189_legacy_resume_remediation6.py`.
- Impacted legacy proposal/route/compiler/Resume/workflow focused suites.
- `PYTHONPATH=backend .venv/bin/python -m compileall -q backend/workbench tests`.
- `git diff --check`.
- Formal line verify and retrospective generation.

Known gates remaining outside this line: browser acceptance, external provider
runtime, host restart, multi-worker process deployment, full repository gate,
integration/release/merge/tag. These remain `NOT VERIFIED` unless directly
run and evidenced here.

No dependency installation, root write, other-worktree write, push, PR,
merge, tag, or release operation is authorized.

## Boundary
- Affected paths: `backend/workbench/agent/proposals.py`, `backend/workbench/agent/orchestrator.py`, `backend/workbench/http/agent_routes.py`, `tests/test_v189_legacy_resume_remediation6.py`, `tests/test_v189_legacy_resume_remediation5.py`, `tests/test_v189_legacy_resume_remediation2.py`, `docs/superpowers/objectives/2026-08-20-v1.8.9-p0-legacy-resume-remediation-6-objective.md`, `docs/superpowers/plans/2026-08-20-v1.8.9-p0-legacy-resume-remediation-6.md`, `docs/superpowers/handoff/2026-08-20-v1.8.9-p0-legacy-resume-remediation-6-handoff.md`
- Allowed paths: `backend/workbench/agent/proposals.py`, `backend/workbench/agent/orchestrator.py`, `backend/workbench/http/agent_routes.py`, `tests/test_v189_legacy_resume_remediation6.py`, `tests/test_v189_legacy_resume_remediation5.py`, `tests/test_v189_legacy_resume_remediation2.py`, `docs/superpowers/objectives/2026-08-20-v1.8.9-p0-legacy-resume-remediation-6-objective.md`, `docs/superpowers/plans/2026-08-20-v1.8.9-p0-legacy-resume-remediation-6.md`, `docs/superpowers/handoff/2026-08-20-v1.8.9-p0-legacy-resume-remediation-6-handoff.md`
- Protected paths: `root-checkout`, `other-worktrees`, `predecessor-formal-lines`, `Report`, `data`, `classification`, `survey`, `providers`
- Dependencies: `v1-8-9-p0-legacy-resume-remediation-5`, `v1-8-9-p0-legacy-resume-remediation-4`, `v1-8-9-p0-legacy-resume-remediation-3`, `v1-8-9-p0-legacy-resume-remediation-2`, `v1-8-9-p0-legacy-proposal-binding-remediation`, `v1-8-9-p0-legacy-resume-authority-rehardening`, `v1-8-9-p0-agent-compiler-core`, `v1-8-9-contract-lock`
- Tests: `PYTHONPATH=backend .venv/bin/python -m pytest tests/test_v189_legacy_resume_remediation6.py -q --disable-warnings --maxfail=1`, `isolated compileall backend/workbench tests`, `git diff --check`, `formal verify and retrospective`
- Known gates: `browser acceptance NOT VERIFIED`, `external provider runtime NOT VERIFIED`, `host restart NOT VERIFIED`, `multi-worker deployment NOT VERIFIED`, `full repository gate NOT VERIFIED`, `integration/release/merge/tag NOT VERIFIED`

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

### v1-8-3-b0-authority-verifier-redesign (2026-07-26T09:04:34.000Z)

Completed formal devline v1-8-3-b0-authority-verifier-redesign; final_state=COMPLETED; failure_lesson_keys=none
