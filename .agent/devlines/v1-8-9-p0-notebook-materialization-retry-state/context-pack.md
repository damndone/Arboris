# Frozen Context Pack

Line: `v1-8-9-p0-notebook-materialization-retry-state`
Baseline SHA: `cfd8cc3294f2842ef89cfad207f2831fca13964c`

## Objective
# Workbench v1.8.9 P0 Notebook Materialization Retry State

## Objective

When a typed Notebook option has a persisted Pipeline Draft, a failed
execution returns the option to `selected` so the user can retry. Reusing the
same server-owned materialization must restore the lifecycle to `materialized`
before the next execution callback; otherwise a safe retry is incorrectly
rejected even though the Draft and evidence are still valid.

## Scope

- `backend/workbench/agent/notebook/materialization.py`
- `tests/test_notebook_trace_chain.py`

## Acceptance

- A selected option with an existing valid materialization can be retried and
  transitions back to `materialized` exactly once per retry preparation.
- The retry continues to use the existing Draft identity and binding; no new
  Draft or unpinned source is created.
- Trace evidence records the lifecycle transition and the subsequent
  execution attempt.
- Legacy options remain fail-closed and no execution/confirmation gate is
  weakened.
- Scoped tests, compile, diff check, formal verification, and retrospective
  pass.

## Boundary
- Affected paths: `backend/workbench/agent/notebook/materialization.py`, `tests/test_notebook_trace_chain.py`
- Allowed paths: `backend/workbench/agent/notebook/materialization.py`, `tests/test_notebook_trace_chain.py`
- Protected paths: none
- Dependencies: none
- Tests: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend:tests .venv/bin/pytest -q tests/test_notebook_trace_chain.py`
- Known gates: `full backend integration and production host/provider acceptance remain separate gates`

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

### v1-8-5-c3-recipe-preflight-projection (2026-08-01T21:47:00.000Z)

Completed formal devline v1-8-5-c3-recipe-preflight-projection; final_state=COMPLETED; failure_lesson_keys=c3-gate-dedicated-basetemp, recipe-preflight-before-draft

### v1-8-5-c1-regression-family-admission (2026-08-01T13:48:08.000Z)

Completed formal devline v1-8-5-c1-regression-family-admission; final_state=COMPLETED; failure_lesson_keys=family-column-fields-preserve-elementwise, family-contract-drives-source-schema-validation, family-input-validation-before-genesis, materialization-uses-family-contract-not-ols-heuristic, model-family-field-ownership-fail-closed, normalized-fms-tag-before-start, notebook-delegates-to-shared-family-contract, regression-family-contract-before-admission

### v1-8-5-b1-default-target-registry (2026-08-01T13:00:04.000Z)

Completed formal devline v1-8-5-b1-default-target-registry; final_state=COMPLETED; failure_lesson_keys=default-target-registry-needs-explicit-scope-and-vocabulary, memory-default-source-roundtrip-exact-keys, memory-projection-versioned-authority-boundary

### v1-8-4-open-incidents-remediation (2026-07-31T04:08:00.000Z)

Completed formal devline v1-8-4-open-incidents-remediation; final_state=COMPLETED; failure_lesson_keys=closing-evidence-must-postdate-the-work

### v1-8-4-agent-evidence-loop (2026-07-28T15:52:01.000Z)

Completed formal devline v1-8-4-agent-evidence-loop; final_state=COMPLETED; failure_lesson_keys=agent-completed-operation-evidence-boundary, public-artifact-aggregate-budget

### v1-8-3-integration-acceptance (2026-07-28T12:11:00.000Z)

Completed formal devline v1-8-3-integration-acceptance; final_state=COMPLETED; failure_lesson_keys=formal-cli-command-surface, formal-scope-narrowing, supported-host-containment-required

### v1-8-3-mem3-memory-curator-exact-baseline (2026-07-27T11:35:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator-exact-baseline; final_state=COMPLETED; failure_lesson_keys=curator-contract-first, review-api-awaits-response

### v1-8-3-mem3-memory-curator (2026-07-27T11:10:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator; final_state=CLOSED; failure_lesson_keys=none
