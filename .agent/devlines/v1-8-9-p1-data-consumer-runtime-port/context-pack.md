# Frozen Context Pack

Line: `v1-8-9-p1-data-consumer-runtime-port`
Baseline SHA: `f3836408cf15c3e7380823e5c1b303b4467c7aec`

## Objective
# v1.8.9 P1 Data Consumer Runtime Port Objective

Issue a default server-owned, typed data-execution port from a project, run,
and source snapshot. The production path must reject caller-controlled
filesystem paths, executors, registries, and arbitrary objects. A deliberately
typed injection remains available only as a test seam. Missing, foreign,
stale, and unsupported snapshots must fail closed with stable typed failures.

This line does not change `data_operations.py`, central Agent or Notebook
consumers, Report, frontend, or statistical code.

## Boundary
- Affected paths: `backend/workbench/app.py`, `backend/workbench/agent/runtime_bootstrap.py`, `backend/workbench/agent/provider_runtime_contributions.py`, `backend/workbench/services/data_consumer_execution_resolver.py`, `tests/test_v189_data_host_port.py`, `tests/test_v189_agent_notebook_runtime_bootstrap.py`, `docs/superpowers/objectives/2026-08-20-v1.8.9-p1-data-consumer-runtime-port-objective.md`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-p1-data-consumer-runtime-port.md`, `docs/superpowers/handoff/2026-08-20-v1.8.9-p1-data-consumer-runtime-port-handoff.md`
- Allowed paths: `backend/workbench/app.py`, `backend/workbench/agent/runtime_bootstrap.py`, `backend/workbench/agent/provider_runtime_contributions.py`, `backend/workbench/services/data_consumer_execution_resolver.py`, `tests/test_v189_data_host_port.py`, `tests/test_v189_agent_notebook_runtime_bootstrap.py`, `docs/superpowers/objectives/2026-08-20-v1.8.9-p1-data-consumer-runtime-port-objective.md`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-p1-data-consumer-runtime-port.md`, `docs/superpowers/handoff/2026-08-20-v1.8.9-p1-data-consumer-runtime-port-handoff.md`
- Protected paths: `backend/workbench/data_operations.py`, `backend/workbench/agent/notebook`, `backend/workbench/agent/workflow_capability_registry.py`, `backend/workbench/agent/workflow_capability_adapters.py`, `frontend`, `backend/workbench/reporting`
- Dependencies: `v1-8-9-contract-lock`, `v1-8-9-p0-agent-compiler-core`
- Tests: `tests/test_v189_data_host_port.py`, `tests/test_v189_agent_notebook_runtime_bootstrap.py`
- Known gates: `Focused tests prove local server-owned port/bootstrap only; central consumers, browser, provider, containment/performance, host full gate, remote receipt, merge, and release are NOT VERIFIED.`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
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
