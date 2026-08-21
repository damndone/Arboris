# Frozen Context Pack

Line: `v1-8-9-p0-p7-host-bound-integration-migration`
Baseline SHA: `cfd8cc3294f2842ef89cfad207f2831fca13964c`

## Objective
# Workbench v1.8.9 P0 P7 Host-bound Integration Migration

## Objective

Make P7 integration and acceptance tests exercise the real deployment-owned
workflow host boundary. Tests that need successful workflow execution must
inject an explicit admitted host endpoint through the test seam; tests for
missing authority must assert the typed fail-closed error. Never reintroduce a
default endpoint or accept project/request metadata as host authority.

## Scope

- `tests/test_p7_acceptance_matrix.py`
- `tests/test_p7_workflow_integration.py`

## Acceptance

- P7 success, failure, preflight, provenance, and CLI tests pass with explicit
  host authority or typed blocked outcomes.
- No production fallback endpoint, local key minting, or bypass is added.
- Compile, diff check, formal verify, and retrospective pass.

## Boundary
- Affected paths: `tests/test_p7_acceptance_matrix.py`, `tests/test_p7_workflow_integration.py`
- Allowed paths: `tests/test_p7_acceptance_matrix.py`, `tests/test_p7_workflow_integration.py`
- Protected paths: none
- Dependencies: none
- Tests: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend:tests .venv/bin/pytest -q tests/test_p7_acceptance_matrix.py tests/test_p7_workflow_integration.py`
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

### v1-8-8-agent-chain-hardening (2026-08-10T01:59:47.000Z)

Completed formal devline v1-8-8-agent-chain-hardening; final_state=COMPLETED; failure_lesson_keys=host-gate-calendar-and-projection, host-gate-integration-before-claim, manual-browser-coverage-gap, qa-runner-is-not-cryptographic-witness, report-upstream-retry-visible, typed-failure-fail-closed

### v1-8-4-agent-evidence-loop (2026-07-28T15:52:01.000Z)

Completed formal devline v1-8-4-agent-evidence-loop; final_state=COMPLETED; failure_lesson_keys=agent-completed-operation-evidence-boundary, public-artifact-aggregate-budget

### v1-8-3-integration-acceptance (2026-07-28T12:11:00.000Z)

Completed formal devline v1-8-3-integration-acceptance; final_state=COMPLETED; failure_lesson_keys=formal-cli-command-surface, formal-scope-narrowing, supported-host-containment-required

### v1-8-3-mem3-memory-curator-exact-baseline (2026-07-27T11:35:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator-exact-baseline; final_state=COMPLETED; failure_lesson_keys=curator-contract-first, review-api-awaits-response

### v1-8-3-mem3-memory-curator (2026-07-27T11:10:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator; final_state=CLOSED; failure_lesson_keys=none

### v1-8-8-p7-qa-trust-recovery (2026-08-10T05:02:00.000Z)

Completed formal devline v1-8-8-p7-qa-trust-recovery; final_state=COMPLETED; failure_lesson_keys=formal-test-path-metadata, validate-formal-identifiers-first
