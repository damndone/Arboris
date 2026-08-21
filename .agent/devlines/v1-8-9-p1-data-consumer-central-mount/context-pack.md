# Frozen Context Pack

Line: `v1-8-9-p1-data-consumer-central-mount`
Baseline SHA: `91ee6a05eab2a1892844c8a3057e1e607359a29e`

## Objective
# v1.8.9 P1 data-consumer central mount objective

## Objective

Verify and, only where the contract probes demonstrate a missing behavior,
complete the central data-consumer surface so the server-owned data-operation
manifest, source identity, preview/confirmation lifecycle, immutable effect,
OperationRecord, output ports, and unavailable semantics are consumed by the
Workbench registry without a second capability list or raw-payload fallback.

The central surface must make the existing data-consumer package genuinely
usable from the user-operated editor and preserve the same typed contract used
by Agent and Notebook. A successful confirmation is allowed to render only
after HTTP success, exact source/catalog/request identity, typed effect,
OperationRecord, and declared output ports all match. Native formats that are
not available remain typed unavailable.

## Non-goals

- Do not redesign or duplicate the package-owned data-operation executor,
  metadata authority, filter AST, interchange adapter, or runtime port.
- Do not modify classification ML, statistical estimators, central evidence
  registry, Report model-result semantics, or browser/provider deployment.
- Do not install optional dependencies or claim `.sav`, `.zsav`, or `.dta`
  support without a real reader/writer and round-trip evidence.

## Verification target

The central backend and frontend tests must prove manifest-to-route alignment,
source identity binding, preview-to-confirm replay, exact OperationRecord and
output-port completion, fail-closed unavailable behavior, and that the
registry mounts one canonical schema-driven editor for dataset nodes.

## Boundary
- Affected paths: `backend/workbench/http/data_operation_routes.py`, `frontend/src/workbench/registry/sectionRegistry.ts`, `frontend/src/lineage/detail/sections/DataOperationsSection.tsx`, `tests/test_v189_data_consumer_central_mount.py`, `frontend/src/workbench/registry/sectionRegistry.v189.test.ts`, `frontend/src/lineage/detail/sections/DataOperationsSection.test.tsx`, `tests/test_data_operation_routes.py`
- Allowed paths: `backend/workbench/http/data_operation_routes.py`, `frontend/src/workbench/registry/sectionRegistry.ts`, `frontend/src/lineage/detail/sections/DataOperationsSection.tsx`, `tests/test_v189_data_consumer_central_mount.py`, `frontend/src/workbench/registry/sectionRegistry.v189.test.ts`, `frontend/src/lineage/detail/sections/DataOperationsSection.test.tsx`, `tests/test_data_operation_routes.py`
- Protected paths: `backend/workbench/data_operation_manifest.py`, `backend/workbench/data_operations.py`, `backend/workbench/agent/context_tools.py`, `backend/workbench/agent/notebook/evidence.py`, `backend/workbench/services/results_service.py`, `backend/workbench/predictive_research`, `backend/workbench/evidence`, `frontend/src/report`
- Dependencies: `v1.8.9 P0 central typed evidence mount`
- Tests: `PYTHONPATH=backend .venv/bin/python -m pytest tests/test_v189_data_consumer_central_mount.py -q`, `cd frontend && npm test -- --run src/workbench/registry/sectionRegistry.v189.test.ts src/lineage/detail/sections/DataOperationsSection.test.tsx`
- Known gates: `browser/provider/cross-process/full-gate/release acceptance is separate and remains NOT VERIFIED`

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
