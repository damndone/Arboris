# Frozen Context Pack

Line: `v1-8-9-p1-native-interchange-metadata`
Baseline SHA: `48ce69f9c336d7c19024a6c4fa4025a12744a1ec`

## Objective
# Workbench v1.8.9 P1 native interchange metadata and fail-closed adapter

Complete the native `.sav`, `.zsav`, and `.dta` interchange boundary beyond
numeric round-trip: preserve the supported Workbench variable/value metadata,
return typed metadata on read, and convert adapter failures into explicit
`UNAVAILABLE`/loss-manifest evidence without leaking raw exceptions or leaving
ambiguous partial artifacts.

Required outcomes:

- variable labels and value labels have an explicit pyreadstat mapping in both
  directions where the adapter supports them;
- unsupported metadata is represented by a typed loss manifest, never silently
  discarded;
- non-DataFrame results, corrupt files, adapter failures, and partial writes
  fail closed with stable typed errors and cleanup behavior;
- tests prove real metadata round-trip and the failure matrix;
- no changes to Agent/Notebook/Report authority or model execution.

## Boundary
- Affected paths: `backend/workbench/data_interchange.py`, `tests/test_v189_data_interchange.py`, `docs/superpowers/objectives/2026-08-21-v1.8.9-p1-native-interchange-metadata-objective.md`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-p1-native-interchange-metadata.md`
- Allowed paths: `backend/workbench/data_interchange.py`, `tests/test_v189_data_interchange.py`, `docs/superpowers/objectives/2026-08-21-v1.8.9-p1-native-interchange-metadata-objective.md`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-p1-native-interchange-metadata.md`
- Protected paths: `backend/workbench/agent`, `backend/workbench/evidence`, `backend/workbench/reporting.py`, `frontend`, `backend/workbench/http`
- Dependencies: `v1-8-9-p1-native-interchange-packaging`, `v1-8-9-p1-data-operation-contract-migration`
- Tests: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend:tests .venv/bin/pytest tests/test_v189_data_interchange.py tests/test_v189_data_operation_manifest.py -q --disable-warnings`, `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend:tests .venv/bin/python -m compileall -q backend/workbench`, `git diff --check`
- Known gates: `browser, external provider, cross-process restart, full host gate, clean-install optional dependency execution, merge, tag, and release remain NOT VERIFIED`

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
