# Frozen Context Pack

Line: `v1-8-9-p0-legacy-resume-remediation-2`
Baseline SHA: `8c48813868d789266635990769d783f4603ab346`

## Objective
# Workbench v1.8.9 P0 Legacy/Resume Remediation-2 Objective

Close the remaining P0 bypasses found after the prior legacy/resume
rehardening line at exact baseline `8c48813868d789266635990769d783f4603ab346`.
This remediation line owns the server-side proposal boundary, legacy route
receipt gate, direct historical Agent service boundary, and regression probes.

Required outcomes:

- `compile_for_proposal()` and `bind_proposal()` cannot accept a caller-created
  `ProposalRevision` or a synthetic `proposal:compilation-record` identity.
  The only proposal binding input is a real `ProposalStore` plus the exact
  server proposal id; the implementation rereads the persisted latest
  revision, fingerprint, semantic plan hash, actor/session/project, and scope.
  A missing, forged, stale, or cross-scope server proposal fails closed.
- The legacy route validates the complete server-owned proposal and typed
  confirmation receipt, including a required semantic-plan hash, actor,
  session, project, scope, canonical serialization/digest, tamper state, and
  replay state before `_cutover_authority`, compiler record lookup/record, or
  execution. A first-claim mismatch leaves authority and claim stores
  untouched; the actual spy records `authority/record/execute == []`.
- Direct `WorkbenchOrchestrator.confirm_proposal()` and historical Agent
  operation paths cannot create a pending operation outside the
  `AgentNotebookCompilerV1` server-owned boundary. They either use that
  boundary or return a typed fail-closed error before proposal/operation
  writes; a direct-service negative probe proves this without HTTP.
- Existing `validate_resumed_step_state()` model-branch validation remains
  active, including terminal model steps with no downstream branch consumer,
  and the adversarial probe proves callback/persistence is not reached.
- Focused tests, compileall, diff checks, and formal verification use only
  current remediation-2 evidence. Prior line metrics, including its 341
  passed claim, are historical evidence and are not reused as this line's
  result.

## Boundary

- Affected paths: `backend/workbench/http/agent_routes.py`,
  `backend/workbench/agent/orchestrator.py`,
  `backend/workbench/agent/workflow_runtime.py`,
  `tests/test_v189_agent_notebook_cutover.py`,
  `tests/test_v189_legacy_route_authority.py`,
  `tests/test_v189_resume_authority.py`,
  `tests/test_v189_legacy_resume_remediation2.py`,
  `docs/superpowers/objectives/2026-08-19-v1.8.9-p0-legacy-resume-remediation-2-objective.md`,
  `docs/superpowers/plans/2026-08-19-v1.8.9-p0-legacy-resume-remediation-2.md`
- Allowed paths: exactly the affected paths above
- Protected paths: `backend/workbench/http/runs_routes.py`,
  `backend/workbench/report_view_model.py`, `frontend/src/report`,
  `backend/workbench/engine/stages/estimation.py`,
  `backend/workbench/providers`, all Report/data/classification/survey paths,
  root-level files, and all prior `.agent/devlines/*` records
- Baseline: `8c48813868d789266635990769d783f4603ab346`
- Dependencies: `v1-8-9-p0-legacy-resume-authority-rehardening`,
  `v1-8-9-p0-legacy-proposal-binding-remediation`,
  `v1-8-9-p0-legacy-resume-hardening`,
  `v1-8-9-p0-agent-compiler-core`, `v1-8-9-contract-lock`
- Tests: RED probes followed by GREEN focused legacy route/proposal/compiler,
  resume/workflow, and direct Agent-notebook service suites; isolated
  compileall; `git diff --check`; formal verify; formal retrospective
- Known gates: browser acceptance, provider/external runtime, full repository
  gate, release, merge, and tag remain `NOT VERIFIED`; no dependency install,
  push, PR, or release operation

## Boundary
- Affected paths: `backend/workbench/http/agent_routes.py`, `backend/workbench/agent/orchestrator.py`, `backend/workbench/agent/workflow_runtime.py`, `tests/test_v189_agent_notebook_cutover.py`, `tests/test_v189_legacy_route_authority.py`, `tests/test_v189_resume_authority.py`, `tests/test_v189_legacy_resume_remediation2.py`, `docs/superpowers/objectives/2026-08-19-v1.8.9-p0-legacy-resume-remediation-2-objective.md`, `docs/superpowers/plans/2026-08-19-v1.8.9-p0-legacy-resume-remediation-2.md`
- Allowed paths: `backend/workbench/http/agent_routes.py`, `backend/workbench/agent/orchestrator.py`, `backend/workbench/agent/workflow_runtime.py`, `tests/test_v189_agent_notebook_cutover.py`, `tests/test_v189_legacy_route_authority.py`, `tests/test_v189_resume_authority.py`, `tests/test_v189_legacy_resume_remediation2.py`, `docs/superpowers/objectives/2026-08-19-v1.8.9-p0-legacy-resume-remediation-2-objective.md`, `docs/superpowers/plans/2026-08-19-v1.8.9-p0-legacy-resume-remediation-2.md`
- Protected paths: `backend/workbench/http/runs_routes.py`, `backend/workbench/report_view_model.py`, `frontend/src/report`, `backend/workbench/engine/stages/estimation.py`, `backend/workbench/providers`, `Report`, `data`, `classification`, `survey`, `.agent/devlines`
- Dependencies: `v1-8-9-p0-legacy-resume-authority-rehardening`, `v1-8-9-p0-legacy-proposal-binding-remediation`, `v1-8-9-p0-legacy-resume-hardening`, `v1-8-9-p0-agent-compiler-core`, `v1-8-9-contract-lock`
- Tests: `RED probes: caller-created ProposalRevision, forged proposal id/revision/fingerprint, missing persisted proposal, and no synthetic receipt`, `RED probe: semantic mismatch before authority/record/execute with spy calls=[]`, `RED probe: direct WorkbenchOrchestrator/legacy Agent service path cannot write outside compiler boundary`, `GREEN focused: legacy route/proposal/compiler/resume/workflow/agent-notebook suites`, `PYTHONPATH=backend .venv/bin/python -m compileall -q backend/workbench tests using isolated pycache prefix`, `git diff --check`, `formal verify and retrospective`
- Known gates: `browser acceptance NOT VERIFIED`, `provider/external runtime NOT VERIFIED`, `full repository gate NOT VERIFIED`, `release NOT VERIFIED`, `merge/tag NOT VERIFIED`

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

### v1-8-4-agent-model-composition (2026-07-31T02:50:00.000Z)

Completed formal devline v1-8-4-agent-model-composition; final_state=COMPLETED; failure_lesson_keys=action-mode-route-enforcement, agent-covariance-interpretation-guardrail, agent-provider-and-tool-boundaries, bounded-model-specification-evidence, bounded-node-evidence-visibility, browser-blocked-run-lineage-identity, browser-policy-blocked-ui-acceptance, canonical-terminal-inspection-reuse, checkpoint-host-gate-separation, closing-event-timestamp-must-follow-the-incident, coefficient-batch-limit-protocol, covariance-comparison-interpretation-boundary, declared-white-test-post-estimation, derive-workflow-artifacts-server-side, existing-genesis-route-tests-failed, failed-inspection-retry, fms-event-enums-must-match-contract, fms-event-input-must-be-repository-relative, formal-event-redaction-text-ambiguity, formal-event-requires-real-evidence-digest, genesis-draft-url-visibility, genesis-draft-visibility-regression, global-agent-model-figure-evidence, global-agent-numeric-evidence-transcription, global-agent-workflow-answer-path, historical-proposal-terminal-message, inherited-suite-failures-must-be-baselined, notebook-persisted-lifecycle, notebook-planner-must-recover-to-server-pinned-rerun-target, notebook-planner-proposes-rerun-outside-active-head-lineage, notebook-planning-deadline-must-be-explicit-and-user-aligned, notebook-planning-evidence-admission, notebook-planning-exceeds-visible-timeout-without-terminal-state, notebook-workflow-dependency-shape-correction, notebook-workflow-evidence-bridge, panel-workflow-model-composition, persisted-draft-hydration-before-empty, planning-elapsed-counter-resets-on-remount, post-estimation-must-reproduce-declared-covariance, post-estimation-requires-explicit-step, predictor-residual-diagnostic-evidence, preexisting-backend-suite-failures, progress-clock-anchors-to-attempt, proposal-ready-boundary-updates-call-count, proposal-ready-terminal-state, provider-catalog-expectation-mismatch, provider-catalog-test-alignment, real-run-tests-must-claim-a-clean-slot, rescope-leaf-path-depth, separate-existing-route-failure, structured-evidence-not-prose-token, verified-categorical-indicator-reuse, white-test-auxiliary-rank-stability, white-test-own-rank-policy, workflow-branch-covariance-preservation, workflow-pin-registry-artifact-identity

### v1-8-8-p7-agent-adoption (2026-08-09T03:20:32.000Z)

Completed formal devline v1-8-8-p7-agent-adoption; final_state=COMPLETED; failure_lesson_keys=browser-report-remains-not-verified, declaration-derived-option-boundaries, design-diagnostic-neutral-envelope, generated-tool-schema-runtime-validation, p7-artifact-identity-preserves-repeatability, parent-workflow-owns-child-vocabulary, workflow-errors-preserve-step-cause

### v1-8-3-cf2-dependency-bundles (2026-07-26T14:13:57.917Z)

Completed formal devline v1-8-3-cf2-dependency-bundles; final_state=COMPLETED; failure_lesson_keys=none

### v1-8-8-agent-chain-hardening (2026-08-10T01:59:47.000Z)

Completed formal devline v1-8-8-agent-chain-hardening; final_state=COMPLETED; failure_lesson_keys=host-gate-calendar-and-projection, host-gate-integration-before-claim, manual-browser-coverage-gap, qa-runner-is-not-cryptographic-witness, report-upstream-retry-visible, typed-failure-fail-closed

### p4-data-management (2026-08-08T23:58:00.000Z)

Completed formal devline p4-data-management; final_state=COMPLETED; failure_lesson_keys=branch-local-schema-projection, execute-provider-handler-after-projection, formal-event-vocabulary, formal-start-normalized-tags, mutation-derived-values, mutation-live-projection, mutation-no-silent-dataset-omission, p4-contract-first, preserve-existing-branch-return, review-live-registry-api, strip-composition-fields-at-adapter, typed-adapter-parameter-boundary, typed-preview-field-fidelity
