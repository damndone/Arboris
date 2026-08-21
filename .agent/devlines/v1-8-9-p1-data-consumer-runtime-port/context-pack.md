# Frozen Context Pack

Line: `v1-8-9-p1-data-consumer-runtime-port`
Baseline SHA: `91ee6a05eab2a1892844c8a3057e1e607359a29e`

## Objective
# Workbench v1.8.9 P1 data-consumer runtime port objective

## Objective

Make the existing typed data-consumer execution contract reachable from the
server runtime by default. A project/run-bound resolver must issue a
server-owned execution port for an eligible source snapshot; callers may not
provide filesystem paths, executors, registries, or arbitrary host objects as
authority. Explicit test-host injection remains supported only as a typed
replacement seam. Missing, stale, foreign, or unsupported sources remain
typed unavailable/fail-closed.

This slice establishes the runtime seam only. It does not add new data
operations, redesign the executor, or claim Agent/Notebook/Report consumer
coverage before those consumers are wired and tested separately.

## Acceptance

- application bootstrap installs a default server-owned data execution port;
- resolver binds project/run/source identity and rejects caller authority;
- existing injected host-port tests remain compatible;
- no raw rows, filesystem paths, or arbitrary executor escape the port;
- focused tests, compileall, diff check, and formal verification pass.

## Non-goals

No `.sav/.zsav/.dta` support, no frontend redesign, no Report renderer, no
Survey/classification estimator change, no browser/provider/full-gate/release.

## Boundary
- Affected paths: `backend/workbench/app.py`, `backend/workbench/agent/runtime_bootstrap.py`, `backend/workbench/agent/provider_runtime_contributions.py`, `backend/workbench/services/data_consumer_execution_resolver.py`, `tests/test_v189_data_host_port.py`, `tests/test_v189_agent_notebook_runtime_bootstrap.py`, `docs/superpowers/objectives/2026-08-20-v1.8.9-p1-data-consumer-runtime-port-objective.md`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-p1-data-consumer-runtime-port.md`, `docs/superpowers/handoff/2026-08-20-v1.8.9-p1-data-consumer-runtime-port-handoff.md`
- Allowed paths: `backend/workbench/app.py`, `backend/workbench/agent/runtime_bootstrap.py`, `backend/workbench/agent/provider_runtime_contributions.py`, `backend/workbench/services/data_consumer_execution_resolver.py`, `tests/test_v189_data_host_port.py`, `tests/test_v189_agent_notebook_runtime_bootstrap.py`, `docs/superpowers/objectives/2026-08-20-v1.8.9-p1-data-consumer-runtime-port-objective.md`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-p1-data-consumer-runtime-port.md`, `docs/superpowers/handoff/2026-08-20-v1.8.9-p1-data-consumer-runtime-port-handoff.md`
- Protected paths: `backend/workbench/predictive_research`, `backend/workbench/evidence`, `frontend/src`
- Dependencies: `v1-8-9-contract-lock`, `v1-8-9-p1-data-consumer-central-mount`
- Tests: `PYTHONPATH=backend .venv/bin/pytest tests/test_v189_data_host_port.py tests/test_v189_agent_notebook_runtime_bootstrap.py -q`
- Known gates: `browser_provider_full_release_not_verified`, `injected_host_port_is_test_seam_only`

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

### v1-8-3-integration-acceptance (2026-07-28T12:11:00.000Z)

Completed formal devline v1-8-3-integration-acceptance; final_state=COMPLETED; failure_lesson_keys=formal-cli-command-surface, formal-scope-narrowing, supported-host-containment-required

### v1-8-4-agent-evidence-loop (2026-07-28T15:52:01.000Z)

Completed formal devline v1-8-4-agent-evidence-loop; final_state=COMPLETED; failure_lesson_keys=agent-completed-operation-evidence-boundary, public-artifact-aggregate-budget

### v1-8-3-mem3-memory-curator-exact-baseline (2026-07-27T11:35:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator-exact-baseline; final_state=COMPLETED; failure_lesson_keys=curator-contract-first, review-api-awaits-response

### v1-8-3-mem3-memory-curator (2026-07-27T11:10:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator; final_state=CLOSED; failure_lesson_keys=none

### v1-8-5-a2-memory-settings-management (2026-08-01T12:19:00.000Z)

Completed formal devline v1-8-5-a2-memory-settings-management; final_state=COMPLETED; failure_lesson_keys=memory-library-management-safe-identification, memory-retrieval-storage-failure-is-503, notebook-memory-server-owned-settings, preference-store-reject-symlink-ancestor, preference-write-complete-before-replace, tdd-red-a2-local-preferences-confirmation

### v1-8-5-a1-local-memory-bootstrap (2026-08-01T11:27:52.000Z)

Completed formal devline v1-8-5-a1-local-memory-bootstrap; final_state=COMPLETED; failure_lesson_keys=tdd-red-local-memory-bootstrap

### v1-8-3-cf4-notebook-provider-injection (2026-07-26T22:45:00.000Z)

Completed formal devline v1-8-3-cf4-notebook-provider-injection; final_state=COMPLETED; failure_lesson_keys=formal-rescope-boundary, tdd-red-before-provider-injection
