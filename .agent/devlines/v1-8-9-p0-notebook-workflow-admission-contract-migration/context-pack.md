# Frozen Context Pack

Line: `v1-8-9-p0-notebook-workflow-admission-contract-migration`
Baseline SHA: `3257663c4236d8184805f658852f4e5a77c73f48`

## Objective
# Workbench v1.8.9 P0 Notebook and Workflow Admission Contract Migration

## Objective

Align historical Notebook and Agent workflow tests with the server-owned
compiler/admission contract. A workflow or Notebook option must carry a valid
scope (including active-head identity) and a server compilation record before
execution; tests must not bypass this by supplying incomplete synthetic scope
or treating a legacy OptionDraft as materializable.

## Scope

- `tests/test_lmm_agent_reach_v187.py`
- `tests/test_notebook_artifact_contract.py`

## Acceptance

- Focused tests pass while preserving fail-closed scope and materialization
  requirements.
- Tests that exercise successful execution create the current typed compiler
  and admission records; tests that exercise historical rejection assert the
  typed error and do not restore a bypass.
- Compile, diff check, formal verify, and retrospective pass.

## Non-goals

Do not weaken `WORKFLOW_SCOPE_MISSING`, Notebook compiler admission, or
confirmation binding in production code.

## Boundary
- Affected paths: `tests/test_lmm_agent_reach_v187.py`, `tests/test_notebook_artifact_contract.py`
- Allowed paths: `tests/test_lmm_agent_reach_v187.py`, `tests/test_notebook_artifact_contract.py`
- Protected paths: none
- Dependencies: none
- Tests: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend:tests .venv/bin/pytest -q tests/test_lmm_agent_reach_v187.py tests/test_notebook_artifact_contract.py`
- Known gates: none

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
