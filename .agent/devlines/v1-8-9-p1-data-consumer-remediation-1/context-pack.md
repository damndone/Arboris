# Frozen Context Pack

Line: `v1-8-9-p1-data-consumer-remediation-1`
Baseline SHA: `4fe3a827db586733f87a161029bd3cae0c1c8fc2`

## Objective
# Objective: Workbench v1.8.9 P1 Data Consumer Remediation 1

## Exact baseline

This fresh implementation line starts from the target worktree product tip
`4fe3a827db586733f87a161029bd3cae0c1c8fc2`. Prior formal lines, their
Context Packs, events, retrospectives, handoffs, and commits are historical
evidence only and must not be edited.

## Required remediation

Close the independently reviewed P1-A through P1-C and P2-D through P2-F
data-consumer defects within the package-local consumer boundary:

- Separate dependency installation presence from verified import/operation
  admission. A real import or minimal verified adapter failure for pyarrow or
  pyreadstat must produce typed `optional_dependency`/`unavailable` results;
  capability discovery, writer, read, read-back, and manifest/admission paths
  must fail closed without fallback or a bare `ModuleNotFoundError`.
- Route bounded Parquet reads in `data_operations.py` through the same verified
  Parquet engine admission as interchange, passing the admitted engine where
  the pandas contract permits it.
- Before any raw snapshot copy/write, verify run-root containment, reject
  symlink/non-regular/identity hazards, and preserve typed fail-closed errors
  with zero out-of-root side effects.
- Make `MetadataRegistryV1` server-owned metadata deeply immutable or deeply
  copied while retaining compatible serialization.
- Reject malformed non-Mapping column metadata with a typed invalid/unavailable
  or metadata-loss result; never silently drop it or report verified loss-free
  interchange.
- Require value, schema, and dtype agreement for `verified` round-trips;
  mismatches must be represented as schema mismatch or metadata loss rather
  than being hidden behind `value_equal`.

## TDD evidence required

Add and retain minimal RED/GREEN regression tests for broken imports,
unavailable Parquet bypass, symlink pre-write zero side effect, nested metadata
mutation, malformed column metadata, and dtype/schema mismatch. Preserve the
normal CSV/XLSX/Parquet round-trip contracts and typed fastparquet/neither and
pyreadstat-unavailable outcomes.

## Scope and boundaries

Only package-local Data Consumer implementation, its focused tests, objective
and final handoff, and formal development-line files are in scope. Do not
modify central Agent/Notebook/Report/cutover code, providers, frontend product
code, dependencies, other worktrees, or prior formal lines. Do not install
dependencies, sign/broadcast anything, or claim browser/provider/central/
host/full-gate/release acceptance.

## Verification and known gates

Run exact backend interchange, ingestion, data-operation, editor, route, and
manifest tests; direct adversarial probes; frontend focused tests and
typecheck; backend compileall; and `git diff --check`. Run formal verify and
CLI-generated retrospective before closeout. Browser acceptance, provider
integration, central Agent/Notebook/Report integration, host gate, full gate,
merge, tag, and release remain `NOT VERIFIED` unless separately evidenced.

## Boundary
- Affected paths: `docs/superpowers/objectives/2026-08-19-v1.8.9-p1-data-consumer-remediation-1-objective.md`, `docs/superpowers/handoff/2026-08-19-v1.8.9-p1-data-consumer-remediation-1-handoff.md`, `backend/workbench/data_interchange.py`, `backend/workbench/data_operation_manifest.py`, `backend/workbench/data_operations.py`, `backend/workbench/ingestion.py`, `backend/workbench/metadata.py`, `tests/test_v189_data_interchange.py`, `tests/test_v189_data_operation_manifest.py`, `tests/test_ingestion_metadata.py`, `tests/test_data_operations.py`
- Allowed paths: `docs/superpowers/objectives/2026-08-19-v1.8.9-p1-data-consumer-remediation-1-objective.md`, `docs/superpowers/handoff/2026-08-19-v1.8.9-p1-data-consumer-remediation-1-handoff.md`, `backend/workbench/data_interchange.py`, `backend/workbench/data_operation_manifest.py`, `backend/workbench/data_operations.py`, `backend/workbench/ingestion.py`, `backend/workbench/metadata.py`, `tests/test_v189_data_interchange.py`, `tests/test_v189_data_operation_manifest.py`, `tests/test_ingestion_metadata.py`, `tests/test_data_operations.py`
- Protected paths: `.agent/devlines/v1-8-9-p1-data-consumer`, `.agent/devlines/v1-8-9-p1-data-consumer-parquet-matrix-remediation`, `.agent/devlines/v1-8-9-p1-data-consumer-real-remediation`, `.agent/devlines/v1-8-9-p1-data-consumer-formal-closeout`, `backend/workbench/agent`, `backend/workbench/providers`, `frontend/src/agent`, `frontend/src/notebook`, `frontend/src/report`, `frontend/src/workbench/registry/sectionRegistry.ts`, `frontend/src/lineage`, `scripts/gate.sh`
- Dependencies: `pandas`, `pyarrow`, `fastparquet`, `pyreadstat`, `openpyxl`
- Tests: `PYTHONPATH=backend .venv/bin/pytest -q tests/test_v189_data_interchange.py tests/test_ingestion_metadata.py tests/test_data_operations.py`, `PYTHONPATH=backend .venv/bin/pytest -q tests/test_v189_data_consumer_editor.py tests/test_data_operation_routes.py tests/test_v189_data_operation_manifest.py`, `frontend focused registry/editor/route vitest`, `frontend npm run typecheck`, `PYTHONPATH=backend .venv/bin/python -m compileall -q backend`, `git diff --check`, `formal verify and retrospective`
- Known gates: `browser acceptance NOT VERIFIED`, `provider integration NOT VERIFIED`, `central Agent/Notebook/Report integration NOT VERIFIED`, `host gate NOT VERIFIED`, `full gate NOT VERIFIED`, `merge NOT VERIFIED`, `tag NOT VERIFIED`, `release NOT VERIFIED`

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

### v1-8-3-cf4-admission-control (2026-07-26T15:04:30.000Z)

Completed formal devline v1-8-3-cf4-admission-control; final_state=COMPLETED; failure_lesson_keys=evidence-admission-separation, fail-closed-admission
