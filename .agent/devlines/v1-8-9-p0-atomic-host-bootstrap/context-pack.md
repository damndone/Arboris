# Frozen Context Pack

Line: `v1-8-9-p0-atomic-host-bootstrap`
Baseline SHA: `91ee6a05eab2a1892844c8a3057e1e607359a29e`

## Objective
# Work order: v1.8.9 P0 atomic host bootstrap

## Objective

Close the production-host boundary for the shared Agent/Notebook runtime. A
host must be able to validate and install the compiler, Report evidence owner,
and server identity resolvers as one explicit, server-owned composition. No
client request may create or partially configure this bundle.

## Required behavior

1. Require the exact project/session scope and all host authorities explicitly.
2. Validate every contribution before mutating application state.
3. On any validation or composition failure, preserve the previous application
   state byte-for-byte at the binding level.
4. On success, bind one compiler, one Report owner, and both identity seams to
   the same application instance and exact scope.
5. Keep missing host authorities fail-closed; do not infer identity, provider,
   evidence persistence, or data roots.

## Non-goals

- No statistical estimator changes.
- No HTTP client-controlled bootstrap.
- No provider execution or browser acceptance claim.
- No merge, push, tag, release, or deployment mutation.

## Verification boundary

Focused contract tests and `git diff --check` prove this composition boundary
only. Browser, external-provider, cross-process, full-gate, and release
acceptance remain separate evidence layers.

## Boundary
- Affected paths: `backend/workbench/app.py`, `tests/test_v189_agent_notebook_host_bootstrap.py`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-p0-host-bootstrap-atomic.md`
- Allowed paths: `backend/workbench/app.py`, `tests/test_v189_agent_notebook_host_bootstrap.py`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-p0-host-bootstrap-atomic.md`
- Protected paths: `backend/workbench/evidence`, `backend/workbench/report_view_model.py`, `backend/workbench/engine`
- Dependencies: `v1-8-9-contract-lock`, `v1-8-9-p0-evidence-core`, `v1-8-9-p0-agent-compiler-core`
- Tests: `PYTHONPATH=backend .venv/bin/python -m pytest tests/test_v189_agent_notebook_host_bootstrap.py -q --disable-warnings`, `git diff --check`
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
### v1-8-3-integration-acceptance (2026-07-28T12:11:00.000Z)

Completed formal devline v1-8-3-integration-acceptance; final_state=COMPLETED; failure_lesson_keys=formal-cli-command-surface, formal-scope-narrowing, supported-host-containment-required

### v1-8-8-statistical-truth-cleanup (2026-08-13T10:11:25.000Z)

Completed formal devline v1-8-8-statistical-truth-cleanup; final_state=COMPLETED; failure_lesson_keys=none

### v1-8-5-a2-memory-settings-management (2026-08-01T12:19:00.000Z)

Completed formal devline v1-8-5-a2-memory-settings-management; final_state=COMPLETED; failure_lesson_keys=memory-library-management-safe-identification, memory-retrieval-storage-failure-is-503, notebook-memory-server-owned-settings, preference-store-reject-symlink-ancestor, preference-write-complete-before-replace, tdd-red-a2-local-preferences-confirmation

### v1-8-5-a1-local-memory-bootstrap (2026-08-01T11:27:52.000Z)

Completed formal devline v1-8-5-a1-local-memory-bootstrap; final_state=COMPLETED; failure_lesson_keys=tdd-red-local-memory-bootstrap

### v1-8-4-agent-evidence-loop (2026-07-28T15:52:01.000Z)

Completed formal devline v1-8-4-agent-evidence-loop; final_state=COMPLETED; failure_lesson_keys=agent-completed-operation-evidence-boundary, public-artifact-aggregate-budget

### v1-8-3-mem3-memory-curator-exact-baseline (2026-07-27T11:35:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator-exact-baseline; final_state=COMPLETED; failure_lesson_keys=curator-contract-first, review-api-awaits-response

### v1-8-3-mem3-memory-curator (2026-07-27T11:10:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator; final_state=CLOSED; failure_lesson_keys=none

### v1-8-3-cf4-notebook-provider-injection (2026-07-26T22:45:00.000Z)

Completed formal devline v1-8-3-cf4-notebook-provider-injection; final_state=COMPLETED; failure_lesson_keys=formal-rescope-boundary, tdd-red-before-provider-injection
