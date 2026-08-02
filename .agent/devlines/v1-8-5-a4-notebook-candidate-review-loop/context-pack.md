# Frozen Context Pack

Line: `v1-8-5-a4-notebook-candidate-review-loop`
Baseline SHA: `e30fee456b9fa47d3a7e4ae85b1cd03ea39a84fa`

## Objective
# v1.8.5 A4 — Notebook Candidate Review Loop

This is a narrow integration slice of
`docs/superpowers/specs/2026-07-31-v1.8.5-typed-memory-and-model-family-design.md`.
It closes the existing A2/A3 product loop without changing the memory contract
or execution authority.

## Objective

Make the existing server-owned domain-memory candidate queue reachable from the
Notebook surface: load pending candidates for the current project, render the
bounded review controls already defined by `NotebookSurface`, and send explicit
approve/reject decisions back to the current project scope. Candidate review
must remain memory publication only; it must never execute an analysis or alter
Notebook proposal authority.

## Scope

- Update `frontend/src/notebook/NotebookRouteView.tsx` to load the current
  project's candidate queue with lifecycle-safe refresh and stale-project
  guards.
- Pass the queue and an explicit review callback to `NotebookSurface`.
- Use the existing `domainMemoryApi` and `DomainMemoryReviewQueue`; do not add
  another candidate endpoint or a second Settings implementation.
- Add focused frontend tests for queue loading, explicit review dispatch,
  project switching, and fail-closed queue errors.

## Explicit non-scope

- No new memory kinds, apply modes, verifiers, retrieval rules, or target
  contracts.
- No automatic approval, automatic execution, proposal mutation, or analysis
  run.
- No backend route change, no new persistent store, and no browser navigation
  workaround.

## Acceptance

1. A current project with a pending queue renders the existing review controls;
   approval and rejection call the server-owned API with the candidate revision.
2. A queue failure is visible and fail-closed; it does not hide Settings or
   create a local fallback candidate.
3. Switching projects cannot apply a former project's queue, busy state, or
   review result to the new project.
4. The focused Notebook/Memory frontend tests and TypeScript check pass.

## Boundary
- Affected paths: `frontend/src/notebook/NotebookRouteView.tsx`, `frontend/src/notebook/NotebookRouteView.notebook.test.tsx`
- Allowed paths: `frontend/src/notebook/NotebookRouteView.tsx`, `frontend/src/notebook/NotebookRouteView.notebook.test.tsx`, `docs/superpowers/specs/2026-08-01-v1.8.5-a4-notebook-candidate-review-loop-objective.md`
- Protected paths: `backend/workbench`, `frontend/src/notebook/NotebookSurface.tsx`, `frontend/src/workbench`
- Dependencies: `A2/A3 domain-memory candidate API and review component`
- Tests: `cd frontend && ./node_modules/.bin/vitest run src/notebook/NotebookRouteView.notebook.test.tsx src/notebook/DomainMemoryReviewQueue.notebook.test.tsx`, `cd frontend && ./node_modules/.bin/tsc --noEmit`, `git diff --check`
- Known gates: `Browser acceptance must remain separate; do not bypass in-app browser URL policy with direct HTTP`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
### v1-8-5-b1-default-target-registry (2026-08-01T13:00:04.000Z)

Completed formal devline v1-8-5-b1-default-target-registry; final_state=COMPLETED; failure_lesson_keys=default-target-registry-needs-explicit-scope-and-vocabulary, memory-default-source-roundtrip-exact-keys, memory-projection-versioned-authority-boundary

### v1-8-5-a2-memory-settings-management (2026-08-01T12:19:00.000Z)

Completed formal devline v1-8-5-a2-memory-settings-management; final_state=COMPLETED; failure_lesson_keys=memory-library-management-safe-identification, memory-retrieval-storage-failure-is-503, notebook-memory-server-owned-settings, preference-store-reject-symlink-ancestor, preference-write-complete-before-replace, tdd-red-a2-local-preferences-confirmation

### v1-8-4-agent-model-composition (2026-07-31T02:50:00.000Z)

Completed formal devline v1-8-4-agent-model-composition; final_state=COMPLETED; failure_lesson_keys=action-mode-route-enforcement, agent-covariance-interpretation-guardrail, agent-provider-and-tool-boundaries, bounded-model-specification-evidence, bounded-node-evidence-visibility, browser-blocked-run-lineage-identity, browser-policy-blocked-ui-acceptance, canonical-terminal-inspection-reuse, checkpoint-host-gate-separation, closing-event-timestamp-must-follow-the-incident, coefficient-batch-limit-protocol, covariance-comparison-interpretation-boundary, declared-white-test-post-estimation, derive-workflow-artifacts-server-side, existing-genesis-route-tests-failed, failed-inspection-retry, fms-event-enums-must-match-contract, fms-event-input-must-be-repository-relative, formal-event-redaction-text-ambiguity, formal-event-requires-real-evidence-digest, genesis-draft-url-visibility, genesis-draft-visibility-regression, global-agent-model-figure-evidence, global-agent-numeric-evidence-transcription, global-agent-workflow-answer-path, historical-proposal-terminal-message, inherited-suite-failures-must-be-baselined, notebook-persisted-lifecycle, notebook-planner-must-recover-to-server-pinned-rerun-target, notebook-planner-proposes-rerun-outside-active-head-lineage, notebook-planning-deadline-must-be-explicit-and-user-aligned, notebook-planning-evidence-admission, notebook-planning-exceeds-visible-timeout-without-terminal-state, notebook-workflow-dependency-shape-correction, notebook-workflow-evidence-bridge, panel-workflow-model-composition, persisted-draft-hydration-before-empty, planning-elapsed-counter-resets-on-remount, post-estimation-must-reproduce-declared-covariance, post-estimation-requires-explicit-step, predictor-residual-diagnostic-evidence, preexisting-backend-suite-failures, progress-clock-anchors-to-attempt, proposal-ready-boundary-updates-call-count, proposal-ready-terminal-state, provider-catalog-expectation-mismatch, provider-catalog-test-alignment, real-run-tests-must-claim-a-clean-slot, rescope-leaf-path-depth, separate-existing-route-failure, structured-evidence-not-prose-token, verified-categorical-indicator-reuse, white-test-auxiliary-rank-stability, white-test-own-rank-policy, workflow-branch-covariance-preservation, workflow-pin-registry-artifact-identity

### v1-8-4-agent-evidence-loop (2026-07-28T15:52:01.000Z)

Completed formal devline v1-8-4-agent-evidence-loop; final_state=COMPLETED; failure_lesson_keys=agent-completed-operation-evidence-boundary, public-artifact-aggregate-budget

### v1-8-3-integration-acceptance (2026-07-28T12:11:00.000Z)

Completed formal devline v1-8-3-integration-acceptance; final_state=COMPLETED; failure_lesson_keys=formal-cli-command-surface, formal-scope-narrowing, supported-host-containment-required

### v1-8-3-mem3-memory-curator-exact-baseline (2026-07-27T11:35:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator-exact-baseline; final_state=COMPLETED; failure_lesson_keys=curator-contract-first, review-api-awaits-response

### v1-8-3-mem3-memory-curator (2026-07-27T11:10:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator; final_state=CLOSED; failure_lesson_keys=none
