# Frozen Context Pack

Line: `v1-8-9-p0-workflow-seam-scope-admission`
Baseline SHA: `afc7649c81eb54ee8adcb89edc6be14fc8378d6f`

## Objective
# Workbench v1.8.9 P0 Workflow Seam Scope Admission

## Objective

Update the legacy workflow seam fixtures so they supply the compiler's typed
scope admission (`context_fingerprint`, target run, and active head) before
testing dataset bindings, replay, chained outputs, resume, and identity
invalidation. Preserve each test's original assertion about lineage or
binding; do not relax the compiler's scope requirement.

## Scope

- `tests/test_workflow_seam.py`

## Acceptance

- Focused workflow seam tests pass after the fixture admission correction.
- Tests for missing/foreign/stale/unknown bindings still reach their intended
  typed failure rather than failing earlier with missing scope.
- No production default scope, implicit active head, or unbound fallback is
  introduced.

## Boundary

- Affected paths: `tests/test_workflow_seam.py`
- Allowed paths: `tests/test_workflow_seam.py`
- Protected paths: production compiler/workflow scope validation
- Dependencies: current v1.8.9 workflow compiler receipt contract
- Tests: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend:tests .venv/bin/pytest -q tests/test_workflow_seam.py`
- Known gates: full backend, browser, production host/provider, and release gates remain separate

## Boundary
- Affected paths: `tests/test_workflow_seam.py`
- Allowed paths: `tests/test_workflow_seam.py`
- Protected paths: `backend/workbench/agent/workflow.py`, `backend/workbench/agent/workflow_runtime.py`
- Dependencies: `v1.8.9 workflow compiler receipt scope contract`
- Tests: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend:tests .venv/bin/pytest -q tests/test_workflow_seam.py`
- Known gates: `full backend, browser, production host/provider, and release acceptance remain separate`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_markdown":"# Global Development Rules\n\nGenerated from repeated devline events. Mandatory rules have appeared at least three times.\n\n- `REVIEW|persistence_capability_bypass|filesystem persistence capability bypass` — A sealed input is insufficient when packet and index writes retain a raw-path escape. (resolution: define admission-gated FD-only writer)\n","global_rules_markdown_sha256":"b619424541a214099df16821c0642f4b2ddb9ee498f66cce7dece275b1117fe5","global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"7d2646296aff49c2c92e83e53f6ad44990aec4280746ec5cf7d9f40b3ab87598"}
```

## Mandatory global development rules
# Global Development Rules

Generated from repeated devline events. Mandatory rules have appeared at least three times.

- `REVIEW|persistence_capability_bypass|filesystem persistence capability bypass` — A sealed input is insufficient when packet and index writes retain a raw-path escape. (resolution: define admission-gated FD-only writer)

## Selected historical lessons
### v1-8-8-statistical-truth-cleanup (2026-08-13T10:11:25.000Z)

Completed formal devline v1-8-8-statistical-truth-cleanup; final_state=COMPLETED; failure_lesson_keys=none

### v1-8-8-agent-chain-hardening (2026-08-10T01:59:47.000Z)

Completed formal devline v1-8-8-agent-chain-hardening; final_state=COMPLETED; failure_lesson_keys=host-gate-calendar-and-projection, host-gate-integration-before-claim, manual-browser-coverage-gap, qa-runner-is-not-cryptographic-witness, report-upstream-retry-visible, typed-failure-fail-closed

### v1-8-8-p7-agent-adoption (2026-08-09T03:20:32.000Z)

Completed formal devline v1-8-8-p7-agent-adoption; final_state=COMPLETED; failure_lesson_keys=browser-report-remains-not-verified, declaration-derived-option-boundaries, design-diagnostic-neutral-envelope, generated-tool-schema-runtime-validation, p7-artifact-identity-preserves-repeatability, parent-workflow-owns-child-vocabulary, workflow-errors-preserve-step-cause

### p5-reachability-gaps (2026-08-09T00:16:00.000Z)

Completed formal devline p5-reachability-gaps; final_state=COMPLETED; failure_lesson_keys=p5-reachability-contract-before-implementation, p5-source-commitment-lineage

### p4-data-management (2026-08-08T23:58:00.000Z)

Completed formal devline p4-data-management; final_state=COMPLETED; failure_lesson_keys=branch-local-schema-projection, execute-provider-handler-after-projection, formal-event-vocabulary, formal-start-normalized-tags, mutation-derived-values, mutation-live-projection, mutation-no-silent-dataset-omission, p4-contract-first, preserve-existing-branch-return, review-live-registry-api, strip-composition-fields-at-adapter, typed-adapter-parameter-boundary, typed-preview-field-fidelity

### v1-8-4-agent-evidence-loop (2026-07-28T15:52:01.000Z)

Completed formal devline v1-8-4-agent-evidence-loop; final_state=COMPLETED; failure_lesson_keys=agent-completed-operation-evidence-boundary, public-artifact-aggregate-budget

### v1-8-3-integration-acceptance (2026-07-28T12:11:00.000Z)

Completed formal devline v1-8-3-integration-acceptance; final_state=COMPLETED; failure_lesson_keys=formal-cli-command-surface, formal-scope-narrowing, supported-host-containment-required

### v1-8-3-mem3-memory-curator-exact-baseline (2026-07-27T11:35:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator-exact-baseline; final_state=COMPLETED; failure_lesson_keys=curator-contract-first, review-api-awaits-response

### v1-8-3-mem3-memory-curator (2026-07-27T11:10:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator; final_state=CLOSED; failure_lesson_keys=none
