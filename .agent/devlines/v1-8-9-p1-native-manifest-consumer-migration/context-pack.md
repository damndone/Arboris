# Frozen Context Pack

Line: `v1-8-9-p1-native-manifest-consumer-migration`
Baseline SHA: `91ee6a05eab2a1892844c8a3057e1e607359a29e`

## Objective
# Workbench v1.8.9 P1 native manifest consumer migration

## Objective

Update the adjacent data-consumer contract test to recognize the live,
fail-closed native interchange manifest: `.sav`, `.zsav`, and `.dta` are
listed as unavailable only when the admitted pyreadstat capability is absent
or broken, and are omitted from `unavailable` when real round-trip support is
available. Do not weaken the manifest or make environment-sensitive native
support appear unavailable.

## Required evidence

- RED from the stale consumer assertion under an admitted native adapter;
- GREEN for the adjacent consumer test and native manifest suite;
- formal verification, compileall, and `git diff --check`;
- browser/provider/full-host/cross-process/release remain separate gates.

## Boundary
- Affected paths: `tests/test_v189_data_consumer_editor.py`
- Allowed paths: `tests/test_v189_data_consumer_editor.py`, `docs/superpowers/objectives/2026-08-21-v1.8.9-p1-native-manifest-consumer-migration-objective.md`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-p1-native-manifest-consumer-migration.md`
- Protected paths: `backend/workbench/data_operation_manifest.py`, `.agent/devlines`
- Dependencies: none
- Tests: `PYTHONPATH=backend:tests .venv/bin/pytest tests/test_v189_data_consumer_editor.py tests/test_v189_data_interchange.py tests/test_v189_data_operation_manifest.py -q --disable-warnings`
- Known gates: `browser/provider/full-host/cross-process/release remain NOT VERIFIED`

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
