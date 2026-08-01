# Frozen Context Pack

Line: `v1-8-5-a5-model-packet-lineage-label`
Baseline SHA: `9f199e70c37985497911011413279807c96c0181`

## Objective
# Workbench v1.8.5 A5 — model packet lineage label correctness

## Objective

Ensure the shared estimation-to-lineage boundary derives the model identity
from the authoritative public result payload when a model pack returns a
packet envelope. A packed time-series result must never be displayed as the
legacy `ols (primary)` label in Graph, Table, Report, or downstream evidence.

## Scope

Allowed implementation paths:

- `backend/workbench/engine/stages/estimation.py`
- `tests/engine/test_lmm_execution_admission.py`
- this objective document

The change is limited to the existing `_result_for_downstream` boundary and
its regression tests. It must preserve the LMM packet contract and the direct
result shape of built-in handlers.

## Acceptance

- A packet whose authoritative nested `result.model_type` is
  `time_series.ets` is exposed to legacy downstream stages with that model
  type, so RecordingStage cannot fall back to OLS.
- The existing LMM unwrapping behavior remains unchanged.
- Direct result payloads remain unchanged.
- Focused backend tests and TypeScript/diff checks pass.
- No browser claim is made by this line; browser acceptance remains separate.

## Non-goals

- No model-specific label map in the frontend.
- No special case for ETS.
- No change to result persistence, model selection, or statistical semantics.

## Boundary
- Affected paths: `backend/workbench/engine/stages/estimation.py`, `tests/engine/test_lmm_execution_admission.py`
- Allowed paths: `backend/workbench/engine/stages/estimation.py`, `tests/engine/test_lmm_execution_admission.py`, `docs/superpowers/specs/2026-08-01-v1.8.5-a5-model-packet-lineage-label-objective.md`
- Protected paths: `backend/workbench/engine/stages/recording.py`, `frontend/src`, `docs/superpowers/specs/2026-07-31-v1.8.5-typed-memory-and-model-family-design.md`
- Dependencies: none
- Tests: `PYTHONPATH=backend .venv/bin/pytest -q tests/engine/test_lmm_execution_admission.py`, `cd frontend && ./node_modules/.bin/tsc --noEmit`
- Known gates: `macOS in-app browser acceptance is separate and not claimed by this line`, `full repository gate is not required for this narrow backend boundary change`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
### wo-a-agent (2026-07-20T17:44:54.000Z)

Completed formal devline wo-a-agent; final_state=CLOSED; failure_lesson_keys=filesystem-persistence-capability-bypass

### v1-8-4-agent-evidence-loop (2026-07-28T15:52:01.000Z)

Completed formal devline v1-8-4-agent-evidence-loop; final_state=COMPLETED; failure_lesson_keys=agent-completed-operation-evidence-boundary, public-artifact-aggregate-budget

### v1-8-3-integration-acceptance (2026-07-28T12:11:00.000Z)

Completed formal devline v1-8-3-integration-acceptance; final_state=COMPLETED; failure_lesson_keys=formal-cli-command-surface, formal-scope-narrowing, supported-host-containment-required

### v1-8-3-mem3-memory-curator-exact-baseline (2026-07-27T11:35:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator-exact-baseline; final_state=COMPLETED; failure_lesson_keys=curator-contract-first, review-api-awaits-response

### v1-8-3-mem3-memory-curator (2026-07-27T11:10:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator; final_state=CLOSED; failure_lesson_keys=none
