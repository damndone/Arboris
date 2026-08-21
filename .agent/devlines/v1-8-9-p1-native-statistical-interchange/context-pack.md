# Frozen Context Pack

Line: `v1-8-9-p1-native-statistical-interchange`
Baseline SHA: `91ee6a05eab2a1892844c8a3057e1e607359a29e`

## Objective
# Workbench v1.8.9 P1 native statistical-file interchange

## Objective

Complete the real SPSS/Stata interchange boundary for `.sav`, `.zsav`, and
`.dta` while preserving the existing fail-closed optional-dependency and
metadata-loss contracts. When the admitted native adapter is installed,
Workbench must perform a real write/read round trip for all three formats and
return exact typed evidence for file identity, value equality, schema/dtype
equality, and any metadata that could not be represented. When the adapter is
missing, broken, or only superficially importable, every capability, writer,
reader, manifest, and Agent/Notebook/Report-facing result remains explicitly
`unavailable`; no fake success or raw exception is allowed.

Use the existing `pyreadstat` adapter seam rather than adding a second reader.
Preserve variable labels and value labels where the native format supports
them, and report unsupported measurement-level, user-missing, or other fields
as a typed metadata-loss manifest. Keep path containment, deterministic
cleanup, and real artifact bytes under the existing interchange contract.

## Required evidence

- RED probes for missing/broken adapter and for native round-trip behavior;
- GREEN real `.sav`, compressed `.zsav`, and `.dta` write/read tests when the
  admitted dependency is installed;
- typed unavailable tests for every native surface when the dependency is
  absent or broken;
- manifest/catalog coverage, compileall, and `git diff --check`;
- formal verification and generated retrospective;
- browser, provider, full host, merge, tag, and release remain separate gates.

## Boundary
- Affected paths: `pyproject.toml`, `backend/workbench/data_interchange.py`, `tests/test_v189_data_interchange.py`, `tests/test_v189_data_operation_manifest.py`, `docs/superpowers/objectives/2026-08-21-v1.8.9-p1-native-statistical-interchange-objective.md`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-p1-native-statistical-interchange.md`
- Allowed paths: `pyproject.toml`, `backend/workbench/data_interchange.py`, `tests/test_v189_data_interchange.py`, `tests/test_v189_data_operation_manifest.py`, `docs/superpowers/objectives/2026-08-21-v1.8.9-p1-native-statistical-interchange-objective.md`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-p1-native-statistical-interchange.md`
- Protected paths: `backend/workbench/agent`, `backend/workbench/data_operations.py`, `backend/workbench/http`, `backend/workbench/providers`, `frontend`, `.agent/devlines`
- Dependencies: `v1-8-9-p1-data-consumer-remediation-1`
- Tests: `PYTHONPATH=backend:tests .venv/bin/python -m pytest tests/test_v189_data_interchange.py tests/test_v189_data_operation_manifest.py -q --disable-warnings`, `PYTHONPATH=backend .venv/bin/python -m compileall -q backend/workbench/data_interchange.py tests/test_v189_data_interchange.py tests/test_v189_data_operation_manifest.py`, `git diff --check`
- Known gates: `browser`, `real-provider`, `full-host-gate`, `merge-tag-release`

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
