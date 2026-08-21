# Frozen Context Pack

Line: `v1-8-9-p0-agent-natural-language-route`
Baseline SHA: `91ee6a05eab2a1892844c8a3057e1e607359a29e`

## Objective
# Work order: v1.8.9 P0 Agent natural-language route bridge

## Objective

Connect the ordinary HTTP Agent turn to the same server-owned compiler used by
the explicit Agent/Notebook cutover endpoints. The provider loop remains
durable and budgeted, but analysis requests must reach a typed compiler preview
before any confirmation or execution boundary.

## Required behavior

1. Resolve the real HTTP actor/session/project identity before using a bound
   compiler; URL and model claims remain hints only.
2. Expose a narrow compiler-backed preview tool whose source text is the exact
   user turn and whose optional fields are validated by the shared compiler.
3. When a compiler is bound for the exact scope, do not expose the legacy
   proposal tool as an execution-authority fallback.
4. Preserve AgentCore persistence, step budget, abort, and typed tool evidence.
5. Missing compiler or identity remains a typed unavailable boundary; no direct
   compiler execution or client-shaped confirmation is accepted.

## Non-goals

- No direct execution from a natural-language turn.
- No statistical estimator changes.
- No browser/provider/cross-process/release acceptance claim.
- No merge, push, tag, release, or deployment mutation.

## Verification boundary

Focused route/compiler tests and `git diff --check` prove this bridge only.
Full repository, browser, external-provider, cross-process, and release gates
remain separate.

## Boundary
- Affected paths: `backend/workbench/http/agent_routes.py`, `backend/workbench/agent/orchestrator.py`, `tests/test_v189_agent_natural_language_route.py`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-p0-agent-natural-language-route.md`
- Allowed paths: `backend/workbench/http/agent_routes.py`, `backend/workbench/agent/orchestrator.py`, `tests/test_v189_agent_natural_language_route.py`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-p0-agent-natural-language-route.md`
- Protected paths: `backend/workbench/evidence`, `backend/workbench/report_view_model.py`, `backend/workbench/engine`
- Dependencies: `v1-8-9-p0-atomic-host-bootstrap`, `v1-8-9-contract-lock`, `v1-8-9-p0-agent-compiler-core`
- Tests: `PYTHONPATH=backend:tests .venv/bin/pytest tests/test_v189_agent_natural_language_route.py -q --disable-warnings`, `PYTHONPATH=backend:tests .venv/bin/pytest tests/test_v189_agent_notebook_cutover.py tests/test_agent_routes.py -q --disable-warnings`, `git diff --check`
- Known gates: `Focused tests do not prove browser, external provider, cross-process, full gate or release readiness.`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_markdown":"# Global Development Rules\n\nGenerated from repeated devline events. Mandatory rules have appeared at least three times.\n\n- `REVIEW|persistence_capability_bypass|filesystem persistence capability bypass` — A sealed input is insufficient when packet and index writes retain a raw-path escape. (resolution: define admission-gated FD-only writer)\n","global_rules_markdown_sha256":"b619424541a214099df16821c0642f4b2ddb9ee498f66cce7dece275b1117fe5","global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"7d2646296aff49c2c92e83e53f6ad44990aec4280746ec5cf7d9f40b3ab87598"}
```

## Mandatory global development rules
# Global Development Rules

Generated from repeated devline events. Mandatory rules have appeared at least three times.

- `REVIEW|persistence_capability_bypass|filesystem persistence capability bypass` — A sealed input is insufficient when packet and index writes retain a raw-path escape. (resolution: define admission-gated FD-only writer)

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
