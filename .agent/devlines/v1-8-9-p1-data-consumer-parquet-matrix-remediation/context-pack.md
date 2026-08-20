# Frozen Context Pack

Line: `v1-8-9-p1-data-consumer-parquet-matrix-remediation`
Baseline SHA: `ace99dcc4d6e16c1cd790297d0de581b8c3ebe81`

## Objective
# Objective: v1.8.9 P1 Data Consumer Parquet Capability Matrix Remediation

## Scope

Remediate the package-local Data Consumer Parquet capability contract from the
exact current worktree tip `ace99dcc4d6e16c1cd790297d0de581b8c3ebe81`.

The defect under review is that `backend/workbench/data_interchange.py`
advertises Parquet when either `pyarrow` or `fastparquet` is present, while the
bounded reader in `backend/workbench/ingestion.py` imports and uses only
`pyarrow`. A fastparquet-only environment can therefore be planned as
available and fail at execution with a typed optional-dependency error.

This is a new append-only remediation line. The prior formal lines and their
events, retrospectives, handoffs, and implementation commits are historical
evidence and are immutable for this objective. The product implementation
baseline remains `73a09151aa3ab4eb1cdb2e3c94fca2df93df92b3`.

## Required outcome

1. Make `_parquet_engine`, capability discovery, writer/read-back, and bounded
   ingestion share one truthful engine-admission contract.
2. Prefer a safe fastparquet-only bounded reader only if the existing bounded
   row-count, filtering, and boundary guarantees can be demonstrated without
   installing dependencies. Otherwise conservatively make capability, writer,
   read-back, and bounded ingestion consistently typed
   `optional_dependency`/`unavailable` for fastparquet-only environments.
3. Add controlled dependency-matrix tests for pyarrow-only, fastparquet-only,
   both, and neither. Keep a real current-environment Parquet round-trip and
   bounded-ingestion proof when pyarrow is available.
4. Preserve CSV/XLSX/Parquet round-trip behavior, the canonical
   `DataOperationsRegistrySection` preview/confirm and lineage path, and typed
   unavailable behavior for SAV/ZSAV/DTA when pyreadstat is absent.

## Boundaries

- No dependency installation.
- No edits to the root worktree.
- No edits to prior `.agent/devlines` lines or their evidence.
- No central Agent/Notebook/Report cutover, provider integration, host gate,
  browser acceptance, full gate, merge, tag, or release claim.
- Keep the persistence-capability bypass global rule intact.

## Verification and known gates

Run focused data interchange, ingestion, editor, and route tests; focused
frontend registry/editor tests and frontend typecheck; backend compileall;
`git diff --check`; and formal verify/retrospective. Record the real dependency
matrix (`pyarrow`, `fastparquet`, `pyreadstat`, and relevant XLSX engine) and
the actual round-trip/unavailable result for each format. Browser/provider,
central integration, host, full-gate, merge, and release status remain
`NOT VERIFIED` unless separately evidenced (they are out of scope here).

## Boundary
- Affected paths: `docs/superpowers/objectives/2026-08-19-v1.8.9-p1-data-consumer-parquet-matrix-objective.md`, `docs/superpowers/designs/2026-08-19-v1.8.9-p1-data-consumer-parquet-matrix-design.md`, `docs/superpowers/plans/2026-08-19-v1.8.9-p1-data-consumer-parquet-matrix.md`, `docs/superpowers/handoff/2026-08-19-v1.8.9-p1-data-consumer-parquet-matrix-handoff.md`, `backend/workbench/data_interchange.py`, `backend/workbench/ingestion.py`, `tests/test_v189_data_interchange.py`, `tests/test_ingestion_metadata.py`
- Allowed paths: `docs/superpowers/objectives/2026-08-19-v1.8.9-p1-data-consumer-parquet-matrix-objective.md`, `docs/superpowers/designs/2026-08-19-v1.8.9-p1-data-consumer-parquet-matrix-design.md`, `docs/superpowers/plans/2026-08-19-v1.8.9-p1-data-consumer-parquet-matrix.md`, `docs/superpowers/handoff/2026-08-19-v1.8.9-p1-data-consumer-parquet-matrix-handoff.md`, `backend/workbench/data_interchange.py`, `backend/workbench/ingestion.py`, `tests/test_v189_data_interchange.py`, `tests/test_ingestion_metadata.py`
- Protected paths: `.agent/devlines/v1-8-9-p1-data-consumer`, `.agent/devlines/v1-8-9-p1-data-consumer-formal-closeout`, `.agent/devlines/v1-8-9-p1-data-consumer-real-remediation`, `backend/workbench/agent`, `backend/workbench/providers`, `frontend/src/agent`, `frontend/src/notebook`, `frontend/src/report`, `frontend/src/workbench/registry/sectionRegistry.ts`, `frontend/src/lineage`, `scripts/gate.sh`
- Dependencies: `pyarrow`, `fastparquet`, `pyreadstat`, `openpyxl`
- Tests: `backend focused interchange/ingestion pytest`, `frontend focused editor/registry vitest`, `frontend typecheck`, `backend compileall`, `git diff --check`, `formal verify and retrospective`
- Known gates: `browser acceptance NOT VERIFIED`, `provider integration NOT VERIFIED`, `central Agent/Notebook/Report integration NOT VERIFIED`, `host gate NOT VERIFIED`, `full gate NOT VERIFIED`, `merge NOT VERIFIED`, `release NOT VERIFIED`

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

### v1-8-3-document-authority-consolidation (2026-07-26T03:30:00.000Z)

Completed formal devline v1-8-3-document-authority-consolidation; final_state=COMPLETED; failure_lesson_keys=none
