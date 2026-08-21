# Frozen Context Pack

Line: `v1-8-9-p0-agent-cutover-test-migration`
Baseline SHA: `91ee6a05eab2a1892844c8a3057e1e607359a29e`

## Objective
# Workbench v1.8.9 P0 Agent/Notebook cutover test migration

## Objective

Migrate historical direct calls to the Agent/Notebook cutover HTTP route into
an explicit server-owned test harness after the identity boundary is closed.
Tests must prove that an absent Request fails closed before authority or
repository access, while bound HTTP requests still compile and preserve
server-side confirmation behavior. Do not reintroduce a caller-controlled
identity or a process-global authority shortcut.

## Required evidence

- RED for the stale direct-call fixture after the identity hardening;
- GREEN for the migrated cutover, route identity, natural-language, and
  runtime-bridge tests;
- compileall, diff check, formal verification, and retrospective;
- browser, real provider, supervisor, multi-worker, full-host, merge, tag,
  and release remain separate `NOT VERIFIED` gates.

## Boundary
- Affected paths: `tests/test_v189_agent_notebook_cutover.py`, `tests/test_v189_agent_notebook_runtime_bridge.py`, `tests/test_v189_notebook_cutover_route.py`
- Allowed paths: `tests/test_v189_agent_notebook_cutover.py`, `tests/test_v189_agent_notebook_runtime_bridge.py`, `tests/test_v189_notebook_cutover_route.py`, `docs/superpowers/objectives/2026-08-21-v1.8.9-p0-agent-cutover-test-migration-objective.md`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-p0-agent-cutover-test-migration.md`
- Protected paths: `backend/workbench/http/agent_routes.py`, `backend/workbench/agent/**`, `.agent/devlines`
- Dependencies: none
- Tests: `PYTHONPATH=backend:tests .venv/bin/pytest tests/test_v189_agent_notebook_cutover.py tests/test_v189_agent_notebook_runtime_bridge.py tests/test_v189_notebook_cutover_route.py -q --disable-warnings`
- Known gates: `browser/provider/supervisor/multi-worker/full-host/release remain NOT VERIFIED`

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
