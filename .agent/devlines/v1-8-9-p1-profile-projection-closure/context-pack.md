# Frozen Context Pack

Line: `v1-8-9-p1-profile-projection-closure`
Baseline SHA: `91ee6a05eab2a1892844c8a3057e1e607359a29e`

## Objective
# Workbench v1.8.9 P1 bounded profile projection closure

## Objective

Make the direct data-profile route consume the canonical server-built
`DataProfileV1` shape and project it into the bounded `data-profile.v1`
consumer shape used by the data editor and downstream Agent/Notebook/Report
readers. Preserve fail-closed behavior for malformed, untrusted, or raw
payloads. The adapter must retain dataset identity, observed missingness,
declared labels/value labels/measurement level/user-missing values, safe
samples, and explicit unknown values without exposing paths, rows, or raw
artifacts.

## Required evidence

- RED regression probes showing a confirmed canonical profile currently fails
  at the bounded HTTP projection boundary;
- GREEN for canonical profile projection, profile reload, and existing bounded
  consumer tests;
- adversarial coverage for malformed nested columns and raw/path leakage;
- compileall, `git diff --check`, formal verification, and retrospective;
- browser, provider, cross-process, full-host, merge, tag, and release gates
  remain separate `NOT VERIFIED` evidence.

## Boundaries

- Do not weaken server-owned metadata authority or accept legacy registry data;
- do not expose raw rows, filesystem paths, dataframes, or arbitrary payloads;
- keep the public projection stable and composable for Agent/Notebook/Report;
- no unrelated model-family or provider changes.

## Boundary
- Affected paths: `backend/workbench/http/data_operation_routes.py`, `tests/test_data_operation_routes.py`, `tests/test_v189_data_editor_ui_contract.py`
- Allowed paths: `backend/workbench/http/data_operation_routes.py`, `tests/test_data_operation_routes.py`, `tests/test_v189_data_editor_ui_contract.py`, `docs/superpowers/objectives/2026-08-21-v1.8.9-p1-profile-projection-closure-objective.md`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-p1-profile-projection-closure.md`
- Protected paths: `backend/workbench/data_operations.py`, `backend/workbench/data_profile.py`, `.agent/devlines`
- Dependencies: none
- Tests: `PYTHONPATH=backend:tests .venv/bin/pytest tests/test_data_operation_routes.py tests/test_v189_data_editor_ui_contract.py -q --disable-warnings`
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
