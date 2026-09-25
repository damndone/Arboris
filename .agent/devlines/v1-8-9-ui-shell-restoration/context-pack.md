# Frozen Context Pack

Line: `v1-8-9-ui-shell-restoration`
Baseline SHA: `afc7649c81eb54ee8adcb89edc6be14fc8378d6f`

## Objective
# v1.8.9 Notebook and Graph Agent UI shell restoration

## Objective

Restore the mature v1.8.8 Notebook and Graph Agent interaction quality while keeping the v1.8.9 local-first cutover as the only planning, confirmation, execution, and evidence path.

The repaired surfaces must provide a readable conversation/workspace shell, visible planning progress, structured plan preview, clarification and confirmation states, result/evidence presentation, keyboard-capable composition, and reliable Graph Agent tab reachability. They must not render raw JSON as the primary UI or regress to the retired Notebook/Agent execution APIs.

## Boundaries

- Preserve the existing dirty v1.8.9 candidate and unrelated user work; no reset, checkout, delete, or broad cleanup.
- Frontend-only product change unless a browser probe proves a backend defect.
- Reuse v1.8.8 presentation patterns and existing CSS/components where safe; do not restore `NotebookRouteView`, `AgentSurfaceProvider`, legacy session/option execution, or implicit fallback.
- `cutoverApi` remains the only natural-language compile/confirm/execute transport for both Agent and Notebook.
- Server-owned identity, confirmation, evidence references, and fail-closed errors remain authoritative.
- Do not add a visual companion, a second planner, a second capability table, or unnecessary folders.
- Keep the existing backend, Vite server, and in-app browser tab running throughout acceptance.

## Required verification

- TDD: focused component tests fail on the regressed shell before production edits and pass after restoration.
- Agent tab is reachable from the Graph bottom panel and the compact composer expands it.
- Notebook and Agent previews are structured and readable; raw JSON is not the primary presentation.
- Both surfaces preserve compile -> preview/clarify -> server confirm -> execute -> evidence behavior through `cutoverApi` only.
- Frontend typecheck, focused integration tests, retired-route static scan, and `git diff --check` pass.
- In-app browser acceptance covers Graph Agent and Notebook visible/interactive states on the running local candidate.

## Known gates

- Browser data/setup errors such as a missing notebook must be represented as recoverable product states, not a blank or disabled shell.
- Real external provider quality is outside this UI restoration; deterministic/local cutover behavior is sufficient.
- Linux, other macOS hosts, release merge/tag, and deployment are not part of this line.

## Boundary
- Affected paths: `frontend/src/notebook/NotebookCutoverView.tsx`, `frontend/src/notebook/NotebookCutoverView.test.tsx`, `frontend/src/notebook/notebook.css`, `frontend/src/workbench/agent/AgentCutoverPanel.tsx`, `frontend/src/workbench/agent/AgentCutoverPanel.test.tsx`, `frontend/src/workbench/agent/agent.css`, `frontend/src/workbench/BottomPanel.tsx`, `frontend/src/workbench/registry/bottomPanelRegistry.tsx`, `frontend/src/workbench/WorkbenchRouteContainer.tsx`, `frontend/src/workbench/WorkbenchRouteContainer.test.tsx`, `frontend/src/lineage/graph/NodeActionMenu.tsx`, `frontend/src/lineage/graph/NodeActionMenu.test.tsx`, `frontend/src/cutoverApi.ts`, `frontend/src/cutoverApi.test.ts`, `docs/superpowers/objectives/2026-08-23-v1.8.9-ui-shell-restoration-objective.md`
- Allowed paths: `frontend/src/notebook/NotebookCutoverView.tsx`, `frontend/src/notebook/NotebookCutoverView.test.tsx`, `frontend/src/notebook/notebook.css`, `frontend/src/workbench/agent/AgentCutoverPanel.tsx`, `frontend/src/workbench/agent/AgentCutoverPanel.test.tsx`, `frontend/src/workbench/agent/agent.css`, `frontend/src/workbench/BottomPanel.tsx`, `frontend/src/workbench/registry/bottomPanelRegistry.tsx`, `frontend/src/workbench/WorkbenchRouteContainer.tsx`, `frontend/src/workbench/WorkbenchRouteContainer.test.tsx`, `frontend/src/lineage/graph/NodeActionMenu.tsx`, `frontend/src/lineage/graph/NodeActionMenu.test.tsx`, `frontend/src/cutoverApi.ts`, `frontend/src/cutoverApi.test.ts`, `docs/superpowers/objectives/2026-08-23-v1.8.9-ui-shell-restoration-objective.md`
- Protected paths: `backend`
- Dependencies: none
- Tests: `cd frontend && npm test -- --run src/notebook/NotebookCutoverView.test.tsx src/workbench/agent/AgentCutoverPanel.test.tsx`, `cd frontend && npm run typecheck`, `git diff --check`
- Known gates: `Keep backend, frontend, and the claimed in-app browser tab running until the user explicitly asks to close them.`, `External provider quality, other hosts, deployment, and release integration are out of scope.`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_markdown":"# Global Development Rules\n\nGenerated from repeated devline events. Mandatory rules have appeared at least three times.\n\n- `REVIEW|persistence_capability_bypass|filesystem persistence capability bypass` — A sealed input is insufficient when packet and index writes retain a raw-path escape. (resolution: define admission-gated FD-only writer)\n","global_rules_markdown_sha256":"b619424541a214099df16821c0642f4b2ddb9ee498f66cce7dece275b1117fe5","global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"7d2646296aff49c2c92e83e53f6ad44990aec4280746ec5cf7d9f40b3ab87598"}
```

## Mandatory global development rules
# Global Development Rules

Generated from repeated devline events. Mandatory rules have appeared at least three times.

- `REVIEW|persistence_capability_bypass|filesystem persistence capability bypass` — A sealed input is insufficient when packet and index writes retain a raw-path escape. (resolution: define admission-gated FD-only writer)

## Selected historical lessons
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

### v1-8-8-agent-chain-hardening (2026-08-10T01:59:47.000Z)

Completed formal devline v1-8-8-agent-chain-hardening; final_state=COMPLETED; failure_lesson_keys=host-gate-calendar-and-projection, host-gate-integration-before-claim, manual-browser-coverage-gap, qa-runner-is-not-cryptographic-witness, report-upstream-retry-visible, typed-failure-fail-closed

### v1-8-4-open-incidents-remediation (2026-07-31T04:08:00.000Z)

Completed formal devline v1-8-4-open-incidents-remediation; final_state=COMPLETED; failure_lesson_keys=closing-evidence-must-postdate-the-work
