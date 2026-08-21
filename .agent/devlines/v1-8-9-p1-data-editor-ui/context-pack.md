# Frozen Context Pack

Line: `v1-8-9-p1-data-editor-ui`
Baseline SHA: `91ee6a05eab2a1892844c8a3057e1e607359a29e`

## Objective
# v1.8.9 P1 data editor and metadata UI objective

Expose the already server-owned, bounded data profile and metadata mutation
contract in the direct Workbench data surface. The UI must let a user inspect
verified variable metadata and safe profile values, edit variable/value labels
and user-defined missing values through the existing preview-confirm flow, and
show explicit unavailable/degraded states. It must never render raw file paths,
raw artifacts, or unverified dataframe payloads, and it must remain compatible
with the provider-owned operation manifest so Agent and Notebook can use the
same typed operations.

This is a narrow P1 consumer-surface slice. It does not add a second data
operation engine, bypass server confirmation, or add native statistical-file
decoding.

## Boundary
- Affected paths: `frontend/src/lineage/detail/sections/DataOperationsSection.tsx`, `frontend/src/lineage/detail/sections/DataOperationsSection.test.tsx`, `frontend/src/lineage/dataOperations.ts`, `frontend/src/workbench/registry/sectionRegistry.ts`, `backend/workbench/http/data_operation_routes.py`, `tests/test_v189_data_editor_ui_contract.py`
- Allowed paths: `frontend/src/lineage/detail/sections/DataOperationsSection.tsx`, `frontend/src/lineage/detail/sections/DataOperationsSection.test.tsx`, `frontend/src/lineage/dataOperations.ts`, `frontend/src/workbench/registry/sectionRegistry.ts`, `backend/workbench/http/data_operation_routes.py`, `tests/test_v189_data_editor_ui_contract.py`, `docs/superpowers/objectives/2026-08-21-v1.8.9-p1-data-editor-ui-objective.md`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-p1-data-editor-ui.md`
- Protected paths: `backend/workbench/agent`, `backend/workbench/evidence`, `backend/workbench/providers`, `backend/workbench/agent/authority.py`
- Dependencies: `v1-8-9-p1-data-consumer-projection-readers`
- Tests: `PYTHONPATH=backend:tests .venv/bin/pytest tests/test_v189_data_editor_ui_contract.py tests/test_v189_data_consumer_projection.py -q --disable-warnings`, `cd frontend && npm test -- --run src/lineage/detail/sections/DataOperationsSection.test.tsx`
- Known gates: `browser_visible_acceptance_not_run`, `native_statistical_file_support_optional_dependency`, `full_repository_gate_and_release_not_run`

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
