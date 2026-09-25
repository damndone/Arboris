# Frozen Context Pack

Line: `v1-8-9-p1-data-consumer-interchange-closure`
Baseline SHA: `afc7649c81eb54ee8adcb89edc6be14fc8378d6f`

## Objective
# Workbench v1.8.9 P1 data consumer and interchange closure

Close the audited P1 data-surface gaps without weakening the server-owned
metadata grammar or interchange failure boundaries.

Required outcomes:

- the data editor emits canonical `variable_label` metadata and exposes the
  supported measurement, missing-policy, role, sensitivity, user-missing, and
  value-label fields through the existing preview-confirm flow;
- the metadata profile projection carries the bounded declared fields needed
  by the editor while continuing to redact raw paths and raw rows;
- native and tabular writers stage output and atomically replace a target only
  after a real artifact has been produced and bounded validation succeeds;
- an admitted adapter failure never changes an existing target, and a writer
  that produces no artifact cannot return `written`;
- importing the live data-operation manifest in a fresh process is stable,
  independent of import order;
- corrupted Parquet reads return a stable typed unavailable/adapter failure,
  and do not leak a raw Arrow exception;
- tests prove red-before-green behavior, preserve Agent/Notebook/Report
  evidence authority, and retain explicit metadata-loss reporting.

This line does not add a second data-operation engine, infer metadata from raw
values, weaken confirmation, or claim browser/provider/host/release acceptance.

## Boundary
- Affected paths: `backend/workbench/services/data_consumer_host_resolver.py`
- Allowed paths: `backend/workbench/services/data_consumer_host_resolver.py`
- Protected paths: none
- Dependencies: `v1-8-9-hardening-integration`
- Tests: `PYTHONPATH=backend .venv/bin/python -m pytest -q tests/test_v189_data_interchange.py tests/test_v189_data_operation_manifest.py`, `frontend/node_modules/.bin/vitest run src/lineage/detail/sections/DataOperationsSection.test.tsx`, `git diff --check`
- Known gates: `browser_acceptance_NOT_VERIFIED`, `provider_acceptance_NOT_VERIFIED`, `host_full_gate_NOT_VERIFIED`, `release_NOT_VERIFIED`

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
