# Frozen Context Pack

Line: `v1-8-9-p0-statistical-stage-import-cycle`
Baseline SHA: `48ce69f9c336d7c19024a6c4fa4025a12744a1ec`

## Objective
# Workbench v1.8.9 P0 statistical stage import-cycle and ARMA gate

Remove the production import cycle that prevents the ARMA-GARCH pack runtime
from importing `StatisticalTestsStage`, then migrate the adjacent ARMA public
workflow assertion to the current server-owned Report/evidence boundary. Keep
the statistical algorithms, typed evidence contracts, and fail-closed Report
authority unchanged.

Required outcomes:

- `StatisticalTestsStage` imports without a partially initialized orchestrator
  package;
- the ARMA pack runtime focused tests pass;
- an unbound Report writer remains unavailable rather than silently generating
  `report.html`;
- no raw result or caller-owned Report authority fallback is restored;
- the scoped test, compileall, and diff checks pass.

## Boundary
- Affected paths: `backend/workbench/engine/stages/statistical_tests.py`, `backend/workbench/orchestrator/__init__.py`, `backend/workbench/orchestrator/_errors.py`, `tests/models/arma_garch/test_pack_runtime.py`, `docs/superpowers/objectives/2026-08-21-v1.8.9-p0-statistical-stage-import-cycle-objective.md`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-p0-statistical-stage-import-cycle.md`
- Allowed paths: `backend/workbench/engine/stages/statistical_tests.py`, `backend/workbench/orchestrator/__init__.py`, `backend/workbench/orchestrator/_errors.py`, `tests/models/arma_garch/test_pack_runtime.py`, `docs/superpowers/objectives/2026-08-21-v1.8.9-p0-statistical-stage-import-cycle-objective.md`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-p0-statistical-stage-import-cycle.md`
- Protected paths: `backend/workbench/data_interchange.py`, `backend/workbench/agent`, `backend/workbench/evidence`, `frontend`
- Dependencies: `v1-8-9-p0-legacy-route-integration-migration`, `v1-8-9-p0-workflow-truth-core`
- Tests: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend:tests .venv/bin/pytest tests/models/arma_garch/test_pack_runtime.py -q --disable-warnings`, `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend:tests .venv/bin/python -m compileall -q backend/workbench/engine backend/workbench/orchestrator`, `git diff --check`
- Known gates: `browser, external provider, cross-process restart, full host gate, merge, tag, and release remain NOT VERIFIED`

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

### local-contained-execution (2026-07-20T17:44:54.000Z)

Completed formal devline local-contained-execution; final_state=CLOSED; failure_lesson_keys=none

### wo-a-agent (2026-07-20T17:44:54.000Z)

Completed formal devline wo-a-agent; final_state=CLOSED; failure_lesson_keys=filesystem-persistence-capability-bypass
