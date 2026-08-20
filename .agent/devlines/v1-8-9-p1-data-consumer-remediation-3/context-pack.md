# Frozen Context Pack

Line: `v1-8-9-p1-data-consumer-remediation-3`
Baseline SHA: `779c150e63ac0eba3c24e24aaef673d19f47d426`

## Objective
# Objective: Workbench v1.8.9 P1 Data Consumer Remediation 3

## Exact baseline

This fresh implementation line starts from the exact target worktree product
tip `779c150e63ac0eba3c24e24aaef673d19f47d426`. Prior formal lines, their
Context Packs, events, retrospectives, handoffs, and commits are historical
evidence only and must not be edited.

## Required remediation

Close the two independently reviewed P1 defects in the package-local Data
Consumer pyreadstat boundary:

- If a pyreadstat writer creates the explicitly requested target and then
  raises `RuntimeError`, `write_interchange_frame` must return typed
  `unavailable` with `path=None` and remove only that target created by this
  call. A pre-existing user file must never be removed. `round_trip_frame` must
  apply the same ownership-safe cleanup and leave no partial artifact.
- `_pyreadstat_module` admission must exercise every native writer mode used at
  runtime: bounded real probes for SAV, ZSAV (`compress=True`), and DTA using a
  minimal frame and private temporary files. Any missing/import-broken/probe-
  broken adapter remains typed `unavailable` and the real-adapter test remains
  skipped when `pyreadstat` is not installed.

Do not broaden exception handling to hide unrelated system failures; all
adapter runtime errors at the public native surfaces must become the existing
typed `InterchangeUnavailableError` / typed unavailable result boundary.

## TDD and evidence requirements

Add real fake-adapter regressions first for partial writer cleanup and ZSAV
probe coverage, observe the baseline failures, record the RED evidence through
the formal event stream, then implement the smallest fail-closed fix. Preserve
SAV/DTA/pyarrow/csv/xlsx behavior and metadata/ingestion contracts.

## Scope and boundaries

Only package-local Data Consumer interchange implementation/tests, this
objective, the final handoff, and formal development-line files are in scope.
Do not modify central Agent/Notebook/Report/cutover code, providers,
dependencies, other worktrees, or prior formal lines. Do not install
dependencies, sign/broadcast anything, or claim browser/provider/central/
host/full-gate/merge/tag/release acceptance.

## Verification and known gates

Run focused and impacted backend tests, impacted frontend tests and typecheck,
backend `compileall`, and `git diff --check`; run direct fake-adapter probes
and retain the real-adapter test skip fact. Run formal `verify`, append the
required GATE and state events, and regenerate the retrospective through the
CLI. Browser, provider, central, host, full, merge, tag, and release remain
`NOT VERIFIED`.

## Boundary
- Affected paths: `backend/workbench/data_interchange.py`, `tests/test_v189_data_interchange.py`, `tests/test_v189_data_operation_manifest.py`, `docs/superpowers/objectives/2026-08-20-v1.8.9-p1-data-consumer-remediation-3-objective.md`, `docs/superpowers/handoff/2026-08-20-v1.8.9-p1-data-consumer-remediation-3-handoff.md`
- Allowed paths: `backend/workbench/data_interchange.py`, `tests/test_v189_data_interchange.py`, `tests/test_v189_data_operation_manifest.py`, `docs/superpowers/objectives/2026-08-20-v1.8.9-p1-data-consumer-remediation-3-objective.md`, `docs/superpowers/handoff/2026-08-20-v1.8.9-p1-data-consumer-remediation-3-handoff.md`
- Protected paths: none
- Dependencies: `pandas`, `pyreadstat`
- Tests: `PYTHONPATH=backend .venv/bin/pytest -q tests/test_v189_data_interchange.py`, `PYTHONPATH=backend .venv/bin/pytest -q tests/test_v189_data_interchange.py tests/test_v189_data_operation_manifest.py tests/test_ingestion_metadata.py tests/test_data_operations.py tests/test_data_operation_routes.py tests/test_v189_data_consumer_editor.py tests/test_v189_consumer_projection.py tests/test_v189_consumer_coverage.py`, `frontend: npm test -- --run src/lineage/dataOperations.test.ts src/workbench/registry/sectionRegistry.v189.test.ts`, `frontend: npm run typecheck`, `PYTHONPATH=backend .venv/bin/python -m compileall -q backend`, `git diff --check`
- Known gates: `browser NOT VERIFIED`, `provider NOT VERIFIED`, `central NOT VERIFIED`, `host NOT VERIFIED`, `full NOT VERIFIED`, `merge NOT AUTHORIZED`, `tag NOT AUTHORIZED`, `release NOT VERIFIED`

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
