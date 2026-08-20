# Frozen Context Pack

Line: `v1-8-9-p1-classification-production-remediation-12`
Baseline SHA: `882ae98ace0308ed9d656f092141b8de844f88eb`

## Objective
# Workbench v1.8.9 P1 Classification Production Remediation 12 Objective

Close the P0 artifacts-index integrity evidence gap from exact baseline
`882ae98ace0308ed9d656f092141b8de844f88eb` without changing the completed
remediation-11 line, classification production bindings, Agent/Notebook/Report
typed projections, or the report producer.

At the real repository-to-HTTP seam, the artifacts-index validator must verify
each indexed artifact path is contained by the run root, resolves to a readable
regular file, and has content whose actual SHA-256 equals the indexed digest.
Missing, unreadable, non-regular, or digest-mismatched artifact files must fail
closed as `ARTIFACTS_INDEX_INVALID` with HTTP 500 and no raw exception detail.

An absent or unreadable `artifacts_index.json` is resource unavailable and must
remain `ARTIFACTS_INDEX_UNAVAILABLE` with HTTP 503. Present malformed JSON,
unknown artifact type, duplicate/path/digest/schema violations, and artifact
content integrity violations are invalid and must remain `ARTIFACTS_INDEX_INVALID`
with HTTP 500. The unreadable-index and unreadable-regular-artifact probes must
use controlled monkeypatching where needed; they must not rely on root chmod
behavior.

The valid formal-output fixture must create real artifact bytes and compute its
actual SHA-256. Preserve all existing fail-closed shape/type/path/digest tests,
classification production bindings, and Agent/Notebook/Report typed projection
coverage. Keep the two existing `tests/test_api.py -k artifacts` async fixture
failures as a known gate and do not modify the report producer.

The remediation is limited to:

- `backend/workbench/repository/run_repository.py`
- `tests/test_v189_classification_production.py`
- this objective and its new handoff

Required evidence is TDD RED before production changes, then GREEN for the
classification/repository/HTTP/ReportWorkspace focused suites, frontend
focused suite and typecheck, compileall, diff check, the known
`tests/test_api.py -q -k artifacts` gate, formal verify, and formal
retrospective. Browser acceptance, external provider benchmark, central
integration/cutover, host full gate, merge, tag, and release remain
`NOT VERIFIED`.

## Boundary
- Affected paths: `backend/workbench/repository/run_repository.py`, `tests/test_v189_classification_production.py`, `docs/superpowers/objectives/2026-08-19-v1.8.9-p1-classification-production-remediation-12-objective.md`, `docs/superpowers/handoff/2026-08-19-v1.8.9-p1-classification-production-remediation-12-handoff.md`
- Allowed paths: none
- Protected paths: `backend/workbench/prediction.py`, `backend/workbench/reporting.py`, `backend/workbench/http/notebook_routes.py`
- Dependencies: none
- Tests: `PYTHONPATH=backend .venv/bin/python -m pytest tests/test_v189_classification_production.py -q`, `PYTHONPATH=backend .venv/bin/python -m pytest tests/test_api.py -q -k artifacts`
- Known gates: `tests/test_api.py -q -k artifacts retains two async completed-run fixture failures`, `browser/provider/central/host/full-gate/release are NOT VERIFIED`

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
