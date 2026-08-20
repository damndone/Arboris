# Retrospective — v1-8-9-p1-data-consumer-parquet-matrix-remediation

## Goal

# Objective: v1.8.9 P1 Data Consumer Parquet Capability Matrix Remediation  ## Scope  Remediate the package-local Data Consumer Parquet capability contract from the exact current worktree tip \`ace99dcc4d6e16c1cd790297d0de581b8c3ebe81\`.  The defect under review is that \`backend/workbench/data_interchange.py\` advertises Parquet when either \`pyarrow\` or \`fastparquet\` is present, while the bounded reader in \`backend/workbench/ingestion.py\` imports and uses only \`pyarrow\`. A fastparquet-only environment can therefore be planned as available and fail at execution with a typed optional-dependency error.  This is a new append-only remediation line. The prior formal lines and their events, retrospectives, handoffs, and implementation commits are historical evidence and are immutable for this objective. The product implementation baseline remains \`73a09151aa3ab4eb1cdb2e3c94fca2df93df92b3\`.  ## Required outcome  1. Make \`_parquet_engine\`, capability discovery, writer/read-back, and bounded    ingestion share one truthful engine-admission contract. 2. Prefer a safe fastparquet-only bounded reader only if the existing bounded    row-count, filtering, and boundary guarantees can be demonstrated without    installing dependencies. Otherwise conservatively make capability, writer,    read-back, and bounded ingestion consistently typed    \`optional_dependency\`/\`unavailable\` for fastparquet-only environments. 3. Add controlled dependency-matrix tests for pyarrow-only, fastparquet-only,    both, and neither. Keep a real current-environment Parquet round-trip and    bounded-ingestion proof when pyarrow is available. 4. Preserve CSV/XLSX/Parquet round-trip behavior, the canonical    \`DataOperationsRegistrySection\` preview/confirm and lineage path, and typed    unavailable behavior for SAV/ZSAV/DTA when pyreadstat is absent.  ## Boundaries  - No dependency installation. - No edits to the root worktree. - No edits to prior \`.agent/devlines\` lines or their evidence. - No central Agent/Notebook/Report cutover, provider integration, host gate,   browser acceptance, full gate, merge, tag, or release claim. - Keep the persistence-capability bypass global rule intact.  ## Verification and known gates  Run focused data interchange, ingestion, editor, and route tests; focused frontend registry/editor tests and frontend typecheck; backend compileall; \`git diff --check\`; and formal verify/retrospective. Record the real dependency matrix (\`pyarrow\`, \`fastparquet\`, \`pyreadstat\`, and relevant XLSX engine) and the actual round-trip/unavailable result for each format. Browser/provider, central integration, host, full-gate, merge, and release status remain \`NOT VERIFIED\` unless separately evidenced (they are out of scope here).

## Final status

COMPLETED

## Metrics

- Failure frequency: 2/6 (33.3%; 33.3 per 100 events)
- Repeat rate: 0/2 (0.0%)
- Recurrence rate: 0/2 (0.0%)
- MTTR: median=0 ms (sample=1; unresolved=1)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-20T00:49:38.000Z `parquet_matrix_red`; cause_status: `known`; cause: The new dependency-matrix RED test reproduced the baseline mismatch: fastparquet-only discovery returned engine fastparquet and capability available while bounded ingestion could not share that admitted engine contract.; resolution: `resolved`; lesson: Capability matrices must cover every execution surface, including bounded ingestion, not only the public writer and pandas engine discovery.

## All errors

- None recorded.

## All gaps

- #3 2026-08-20T00:53:33.000Z `fastparquet_bounded_adapter_not_admitted`; cause_status: `known`; cause: fastparquet is not installed in the current environment and no safe bounded adapter was available to verify without installing it; admitting it would recreate the capability-only availability defect.; resolution: `accepted`; lesson: An optional engine is not an admitted capability until every bounded execution surface has a tested safety contract.

## All waste

- None recorded.

## Root causes and solutions

- `bounded-reader-engine-parity`: occurrences=1; cause_status: `known`; root cause: fastparquet is not installed in the current environment and no safe bounded adapter was available to verify without installing it; admitting it would recreate the capability-only availability defect.; solution: `accepted`
- `parquet-capability-matrix`: occurrences=1; cause_status: `known`; root cause: The new dependency-matrix RED test reproduced the baseline mismatch: fastparquet-only discovery returned engine fastparquet and capability available while bounded ingestion could not share that admitted engine contract.; solution: `resolved`

## Added tests

- `tests/test_v189_data_interchange.py::test_parquet_dependency_matrix_has_one_truthful_semantic`

## New rules

- `bounded-reader-engine-parity`: line experience occurrence(s)=1
- `parquet-capability-matrix`: line experience occurrence(s)=1

## Future guidance

- An optional engine is not an admitted capability until every bounded execution surface has a tested safety contract.
- Capability matrices must cover every execution surface, including bounded ingestion, not only the public writer and pandas engine discovery.
- Package-local green evidence must remain separate from browser, provider, central, host, full-gate, merge, and release claims.

## Event index

- #1: `a082489a-990f-497b-a2ac-e38625587115` | 2026-08-20T00:45:35.695Z | STATE_CHANGE/line_started | incident=`ac5ecd9b-e9ae-45cb-8623-26285f10e4e4` | lesson_key=`frozen-context-before-start` | event_sha256=`11e63b5af2b8387f28b5d41a7f96ef567d45e908099ca14a8e6000f0b453fed6`
- #2: `d5bfec7d-3e72-4c4d-a8fd-1c6e3f2b1d0a` | 2026-08-20T00:49:38.000Z | FAILURE/parquet_matrix_red | incident=`0c5e7f91-5dbb-45a4-94f3-2df1aef9b6d9` | lesson_key=`parquet-capability-matrix` | event_sha256=`851a4477e1a01c8f9a8f20ffa01018a75900f3a332536538b1b1404c52bf859f`
- #3: `ebf8372f-3d69-4f74-9d2f-2a1c6b8e5f40` | 2026-08-20T00:53:33.000Z | GAP/fastparquet_bounded_adapter_not_admitted | incident=`7d0e9c4b-1a6f-4e83-b2d5-8f0c3a7e6b91` | lesson_key=`bounded-reader-engine-parity` | event_sha256=`a43591b36565517a5ab0d58e69b4359a70aca21b51da92ce9f016e358c352a2a`
- #4: `f2a6c8d1-4e7b-49f0-a3c5-8d1e6b2f9047` | 2026-08-20T00:53:33.000Z | GATE/parquet_matrix_green | incident=`a9f4e2c7-6b1d-48e5-903a-2f7c1d8b5e64` | lesson_key=`parquet-capability-matrix` | event_sha256=`ecd9545a60658f42ef005839fc27968bdaace90ed285213e4ca4b3454792da9c`
- #5: `c4e8a1f7-2d9b-46b3-8f0e-5a7c1d6b9e24` | 2026-08-20T00:56:12.000Z | REVIEW/scope_boundary_review | incident=`e7b2c9d4-5f1a-48e6-903c-2d7b8a4f6e15` | lesson_key=`unverified-gate-boundaries` | event_sha256=`fe779364b953d7e4435a921f853f0a846eabd39f4992f1e74063b58a0537f6c9`
- #6: `a6f1d3c8-5e9b-42d7-8a0c-4f2e7b1d9c56` | 2026-08-20T00:56:40.000Z | STATE_CHANGE/remediation_completed | incident=`b8e4c1f7-2d9a-46e3-805c-1f7b3a9d5e24` | lesson_key=`remediation-formal-closeout` | event_sha256=`cf9032f93c3d122906e4c542fa7b56705770eaa1900e46bd9330ee3e15f44145`
