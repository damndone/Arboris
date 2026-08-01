# Frozen Context Pack

Line: `v1-8-5-b1-default-target-registry`
Baseline SHA: `9d87a511f9ef07a202ea0349995c28de1dc1f0ea`

## Objective
# v1.8.5 B1 — Default Target Registry Objective

This is the bounded implementation objective for B1 of
`2026-07-31-v1.8.5-typed-memory-and-model-family-design.md`.  The parent
design remains the sole version-scope authority.

## Objective

Replace the OLS-only memory-default table with a server-owned
`DefaultTargetContract` registry.  A current `suggest_default` memory may
fill only an absent, registered Draft default; it never changes evidence,
execution authority, or an explicit user/Agent value.

## Scope

- Register and validate OLS and Panel covariance targets from the same
  contract shape, including the existing cluster/entity prerequisite.
- Carry a complete, server-owned source (`memory_id`, `revision`,
  `target_ref`) through option persistence and revalidation.
- Fail closed for unregistered targets, invalid source, expired verifier,
  vocabulary mismatch, equal-layer conflict, and more than one independent
  writable field.
- Respect priority: explicit current request, then current project memory,
  then current global memory.  Never select a winner through hidden ordering.
- Render target, source revision, method risk, and the prior/restorable value
  on the Notebook option card.

## Explicit non-scope

- No new estimator, execution path, artifact packet, browser-owned write
  surface, or automatic execution.
- No time-series target: B2 must derive those only from a published
  `RecipeContract`.
- No broad retrieval, semantic search, candidate curator, or model-family
  expansion.

## Acceptance

Tests must first fail and then pass for the registered OLS/Panel cases and
for each refusal/priority rule above.  Existing OLS/Panel numerical behavior
must not change.

## Boundary
- Affected paths: `backend/workbench/agent/context_compiler.py`, `backend/workbench/agent/notebook/memory_defaults.py`, `backend/workbench/agent/notebook/materialization.py`, `backend/workbench/agent/notebook/planning_agent.py`, `backend/workbench/agent/notebook/proposal.py`, `backend/workbench/agent/notebook/service.py`, `backend/workbench/agent/workflow_contracts.py`, `backend/workbench/contracts/agent/notebook_option.py`, `backend/workbench/domain_memory/contracts.py`, `backend/workbench/domain_memory/retrieval.py`, `backend/workbench/domain_memory/service.py`, `frontend/src/notebook/contracts.ts`, `frontend/src/notebook/contracts.notebook.test.tsx`, `frontend/src/notebook/domainMemoryContracts.ts`, `frontend/src/notebook/NotebookRouteView.tsx`, `frontend/src/notebook/NotebookRouteView.notebook.test.tsx`, `frontend/src/notebook/OptionCard.tsx`, `frontend/src/notebook/OptionCard.notebook.test.tsx`, `tests/test_notebook_memory_defaults.py`, `tests/test_memory_integration_context.py`, `tests/test_domain_memory_context_injection.py`, `tests/test_domain_memory_retrieval.py`, `tests/test_notebook_materialization.py`, `tests/test_notebook_planning_agent.py`, `tests/test_notebook_routes.py`, `tests/test_panel_covariance.py`
- Allowed paths: `backend/workbench/agent/context_compiler.py`, `backend/workbench/agent/notebook/memory_defaults.py`, `backend/workbench/agent/notebook/materialization.py`, `backend/workbench/agent/notebook/planning_agent.py`, `backend/workbench/agent/notebook/proposal.py`, `backend/workbench/agent/notebook/service.py`, `backend/workbench/agent/workflow_contracts.py`, `backend/workbench/contracts/agent/notebook_option.py`, `backend/workbench/domain_memory/contracts.py`, `backend/workbench/domain_memory/retrieval.py`, `backend/workbench/domain_memory/service.py`, `frontend/src/notebook/contracts.ts`, `frontend/src/notebook/contracts.notebook.test.tsx`, `frontend/src/notebook/domainMemoryContracts.ts`, `frontend/src/notebook/NotebookRouteView.tsx`, `frontend/src/notebook/NotebookRouteView.notebook.test.tsx`, `frontend/src/notebook/OptionCard.tsx`, `frontend/src/notebook/OptionCard.notebook.test.tsx`, `tests/test_notebook_memory_defaults.py`, `tests/test_memory_integration_context.py`, `tests/test_domain_memory_context_injection.py`, `tests/test_domain_memory_retrieval.py`, `tests/test_notebook_materialization.py`, `tests/test_notebook_planning_agent.py`, `tests/test_notebook_routes.py`, `tests/test_panel_covariance.py`
- Protected paths: `backend/workbench/app.py`, `backend/workbench/econometrics/runner.py`, `backend/workbench/http/memory_routes.py`, `backend/workbench/domain_memory/local_preferences.py`, `frontend/src/workbench/MemorySettingsPanel.tsx`, `docs/superpowers/specs/2026-07-31-v1.8.5-typed-memory-and-model-family-design.md`
- Dependencies: `v1-8-5-a1-local-memory-bootstrap`, `v1-8-5-a2-memory-settings-management`
- Tests: `Focused backend: tests/test_notebook_memory_defaults.py tests/test_domain_memory_context_injection.py tests/test_domain_memory_retrieval.py tests/test_notebook_materialization.py tests/test_notebook_planning_agent.py tests/test_notebook_routes.py tests/test_panel_covariance.py`, `Focused frontend: frontend/src/notebook/OptionCard.notebook.test.tsx plus npm run typecheck`
- Known gates: `Run focused backend and frontend tests with UTF-8 locale.`, `Do not run release full gate while Vite/Vitest services are active; browser acceptance is separate.`, `No estimator changes; OLS/Panel numerical behavior must remain unchanged.`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
### v1-8-3-mem3-memory-curator-exact-baseline (2026-07-27T11:35:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator-exact-baseline; final_state=COMPLETED; failure_lesson_keys=curator-contract-first, review-api-awaits-response

### v1-8-3-mem3-memory-curator (2026-07-27T11:10:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator; final_state=CLOSED; failure_lesson_keys=none

### v1-8-3-integration-acceptance (2026-07-28T12:11:00.000Z)

Completed formal devline v1-8-3-integration-acceptance; final_state=COMPLETED; failure_lesson_keys=formal-cli-command-surface, formal-scope-narrowing, supported-host-containment-required

### v1-8-4-agent-evidence-loop (2026-07-28T15:52:01.000Z)

Completed formal devline v1-8-4-agent-evidence-loop; final_state=COMPLETED; failure_lesson_keys=agent-completed-operation-evidence-boundary, public-artifact-aggregate-budget

### v1-8-4-agent-model-composition (2026-07-31T02:50:00.000Z)

Completed formal devline v1-8-4-agent-model-composition; final_state=COMPLETED; failure_lesson_keys=action-mode-route-enforcement, agent-covariance-interpretation-guardrail, agent-provider-and-tool-boundaries, bounded-model-specification-evidence, bounded-node-evidence-visibility, browser-blocked-run-lineage-identity, browser-policy-blocked-ui-acceptance, canonical-terminal-inspection-reuse, checkpoint-host-gate-separation, closing-event-timestamp-must-follow-the-incident, coefficient-batch-limit-protocol, covariance-comparison-interpretation-boundary, declared-white-test-post-estimation, derive-workflow-artifacts-server-side, existing-genesis-route-tests-failed, failed-inspection-retry, fms-event-enums-must-match-contract, fms-event-input-must-be-repository-relative, formal-event-redaction-text-ambiguity, formal-event-requires-real-evidence-digest, genesis-draft-url-visibility, genesis-draft-visibility-regression, global-agent-model-figure-evidence, global-agent-numeric-evidence-transcription, global-agent-workflow-answer-path, historical-proposal-terminal-message, inherited-suite-failures-must-be-baselined, notebook-persisted-lifecycle, notebook-planner-must-recover-to-server-pinned-rerun-target, notebook-planner-proposes-rerun-outside-active-head-lineage, notebook-planning-deadline-must-be-explicit-and-user-aligned, notebook-planning-evidence-admission, notebook-planning-exceeds-visible-timeout-without-terminal-state, notebook-workflow-dependency-shape-correction, notebook-workflow-evidence-bridge, panel-workflow-model-composition, persisted-draft-hydration-before-empty, planning-elapsed-counter-resets-on-remount, post-estimation-must-reproduce-declared-covariance, post-estimation-requires-explicit-step, predictor-residual-diagnostic-evidence, preexisting-backend-suite-failures, progress-clock-anchors-to-attempt, proposal-ready-boundary-updates-call-count, proposal-ready-terminal-state, provider-catalog-expectation-mismatch, provider-catalog-test-alignment, real-run-tests-must-claim-a-clean-slot, rescope-leaf-path-depth, separate-existing-route-failure, structured-evidence-not-prose-token, verified-categorical-indicator-reuse, white-test-auxiliary-rank-stability, white-test-own-rank-policy, workflow-branch-covariance-preservation, workflow-pin-registry-artifact-identity

### v1-8-4-open-incidents-remediation (2026-07-31T04:08:00.000Z)

Completed formal devline v1-8-4-open-incidents-remediation; final_state=COMPLETED; failure_lesson_keys=closing-evidence-must-postdate-the-work

### v1-8-4-reopened-incident-truth (2026-07-31T08:10:00.000Z)

Completed formal devline v1-8-4-reopened-incident-truth; final_state=COMPLETED; failure_lesson_keys=full-gate-requires-non-nested-seatbelt, gate-requires-non-nested-sandbox

### v1-8-3-cf4-binding-provenance (2026-07-27T06:42:00.000Z)

Completed formal devline v1-8-3-cf4-binding-provenance; final_state=COMPLETED; failure_lesson_keys=binding-provenance-contract-red

### v1-8-3-cf4-deterministic-materialization (2026-07-27T04:10:00.000Z)

Completed formal devline v1-8-3-cf4-deterministic-materialization; final_state=COMPLETED; failure_lesson_keys=caller-id-fail-closed, optional-identity-compatibility, provenance-get-or-create-identity, stable-materialization-first

### v1-8-3-cf4-notebook-confirmation-binding (2026-07-27T03:42:45.000Z)

Completed formal devline v1-8-3-cf4-notebook-confirmation-binding; final_state=COMPLETED; failure_lesson_keys=confirmation-contract-first
