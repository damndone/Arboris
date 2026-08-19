# Frozen Context Pack

Line: `v1-8-9-p1-data-consumer`
Baseline SHA: `05362b5697e10eb25fd219da003641f96eeec082`

## Objective
# Workbench v1.8.9 P1 Data Consumer Objective

Complete the safe, composable data-consumer foundation needed by SPSS/Stata
users without turning it into a second execution engine. Add typed metadata
and missing-value semantics, preview-first operations, and manifest/HTTP
coverage for the supported data transformations. Preserve immutable dataset
identity, lineage, server-owned admission, bounded context egress, and
fail-closed behavior.

This line owns the backend data profile/metadata/filter/operation contracts,
the data-operation manifest and HTTP surface, and the existing data-operation
consumer component tests. It may add a reusable editor contribution but does
not change the central Agent/Notebook router or the canonical section registry
mount; central mounting is a later integration task.

Required outcomes:

- variable labels, value labels, measurement roles, user-defined missing
  values, weights, filters, sorting, split-file/group semantics, and batch
  recode have typed contracts with preview, confirmation, identity-bound
  persistence, and lineage;
- existing backend operations are not advertised as reachable unless their
  manifest, HTTP/runtime, and evidence path are real;
- filter expressions remain a bounded AST, never arbitrary code;
- metadata loss is explicit and round-trip checks are available to consumers;
- raw rows and restricted columns remain unavailable to remote contexts by
  default.

Native .sav/.dta interchange is a separately staged adapter within this line
only if the local optional dependency and safe round-trip contract can be
proven; otherwise it must remain a typed unavailable capability rather than a
fake reader/writer.

## Boundary
- Affected paths: `docs/superpowers/objectives/2026-08-19-v1.8.9-p1-data-consumer-objective.md`, `backend/workbench/data_profile.py`, `backend/workbench/metadata.py`, `backend/workbench/filter_ast.py`, `backend/workbench/data_operations.py`, `backend/workbench/data_operation_manifest.py`, `backend/workbench/data_context_egress.py`, `backend/workbench/ingestion.py`, `backend/workbench/data_interchange.py`, `backend/workbench/http/data_operation_routes.py`, `backend/workbench/providers/builtin/data_consumer.json`, `frontend/src/lineage/dataOperationManifest.ts`, `frontend/src/lineage/detail/sections/DataOperationsSection.tsx`, `frontend/src/lineage/detail/sections/DataOperationsSection.test.tsx`, `tests/test_v189_data_profile.py`, `tests/test_v189_filter_ast.py`, `tests/test_v189_data_operation_manifest.py`, `tests/test_v189_data_interchange.py`, `tests/test_v189_data_consumer_editor.py`, `tests/test_data_operation_routes.py`, `docs/superpowers/handoff/2026-08-19-v1.8.9-p1-data-consumer-handoff.md`
- Allowed paths: `docs/superpowers/objectives/2026-08-19-v1.8.9-p1-data-consumer-objective.md`, `backend/workbench/data_profile.py`, `backend/workbench/metadata.py`, `backend/workbench/filter_ast.py`, `backend/workbench/data_operations.py`, `backend/workbench/data_operation_manifest.py`, `backend/workbench/data_context_egress.py`, `backend/workbench/ingestion.py`, `backend/workbench/data_interchange.py`, `backend/workbench/http/data_operation_routes.py`, `backend/workbench/providers/builtin/data_consumer.json`, `frontend/src/lineage/dataOperationManifest.ts`, `frontend/src/lineage/detail/sections/DataOperationsSection.tsx`, `frontend/src/lineage/detail/sections/DataOperationsSection.test.tsx`, `tests/test_v189_data_profile.py`, `tests/test_v189_filter_ast.py`, `tests/test_v189_data_operation_manifest.py`, `tests/test_v189_data_interchange.py`, `tests/test_v189_data_consumer_editor.py`, `tests/test_data_operation_routes.py`, `docs/superpowers/handoff/2026-08-19-v1.8.9-p1-data-consumer-handoff.md`
- Protected paths: `backend/workbench/agent`, `backend/workbench/evidence`, `frontend/src/workbench/registry/sectionRegistry.ts`, `frontend/src/notebook`, `frontend/src/report`, `scripts/gate.sh`
- Dependencies: `v1-8-9-foundation-integration`
- Tests: `PYTHONPATH=backend .venv/bin/python -m pytest tests/test_v189_data_profile.py tests/test_v189_filter_ast.py tests/test_v189_data_operation_manifest.py tests/test_v189_data_interchange.py tests/test_v189_data_consumer_editor.py tests/test_data_operation_routes.py -q`, `cd frontend && npm test -- --run src/lineage/detail/sections/DataOperationsSection.test.tsx`, `cd frontend && npm run typecheck`, `git diff --check`
- Known gates: `central section registry mount is a later integration task`, `optional native .sav/.dta dependency must be proven or remain typed unavailable`, `browser/provider/full gate/release remain separate`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

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

### p4-data-management (2026-08-08T23:58:00.000Z)

Completed formal devline p4-data-management; final_state=COMPLETED; failure_lesson_keys=branch-local-schema-projection, execute-provider-handler-after-projection, formal-event-vocabulary, formal-start-normalized-tags, mutation-derived-values, mutation-live-projection, mutation-no-silent-dataset-omission, p4-contract-first, preserve-existing-branch-return, review-live-registry-api, strip-composition-fields-at-adapter, typed-adapter-parameter-boundary, typed-preview-field-fidelity
