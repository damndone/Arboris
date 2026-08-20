# Retrospective — v1-8-9-p1-classification-production-remediation-17

## Goal

# Workbench v1.8.9 P1 classification production remediation-17 objective  - Exact baseline: \`1a910c6c83d5d57b35d37031ca84b5d8b15b3255\`. - Formal line: \`v1-8-9-p1-classification-production-remediation-17\`. - Scope: correct the independent code-quality P1 in the Workbench-owned   generic artifact Range parser without changing the root checkout or any   other worktree.  ## Required outcome  1. Keep the 64 KiB Range-header and 64-range bounds, Workbench ownership,    single/multipart ranges, \`If-Range\`, compatibility headers, same-FD bounded    streaming, cleanup, and existing 400/416 response boundaries. 2. Enforce a strict ASCII numeric grammar for byte-range components. Any    malformed range component or malformed range-set must fail explicitly with    the existing malformed-range \`400\`; it must never be silently discarded.    For example, \`garbage\` and \`+1-2\` are invalid. 3. Apply RFC byte-range-set semantics after syntax validation: syntactically    valid but unsatisfiable components are ignored when at least one    syntactically valid component is satisfiable; return \`416\` only when no    component is satisfiable. Preserve malformed ordering as \`400\`. 4. Add TDD regression tests for mixed valid/unsatisfiable ranges, mixed valid/    malformed ranges, signed numeric syntax, all-unsatisfiable ranges, and    the existing Range/If-Range/header/stream cleanup boundaries.  ## Allowed paths  - \`backend/workbench/http/runs_routes.py\` - \`tests/test_v189_classification_production.py\` - \`docs/superpowers/objectives/2026-08-20-v1.8.9-p1-classification-production-remediation-17-objective.md\` - \`docs/superpowers/plans/2026-08-20-v1.8.9-p1-classification-production-remediation-17.md\` - \`docs/superpowers/handoff/2026-08-20-v1.8.9-p1-classification-production-remediation-17-handoff.md\` - \`.agent/devlines/v1-8-9-p1-classification-production-remediation-17/**\` (only   through \`scripts/devline_control.py\`).  ## Protected boundaries  - The repository root checkout and every other worktree are out of scope. - Existing remediation-16 formal events, Context Pack, manifest,   retrospective, and handoff are immutable. - \`backend/workbench/repository/file_integrity.py\` is unchanged in this line;   the rem16 64 KiB/512 MiB/same-FD/cleanup/TOCTOU seam remains the consumer. - Classification list/index/consumer seams, central Agent/Notebook/Report   consumers, and the remediation-15 \`consumer_projection\` whole-body residual   are out of scope.  ## Verification contract  - RED, then GREEN focused parser/range tests with   \`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend .venv/bin/python -m pytest -p no:cacheprovider\`. - \`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend .venv/bin/python -m pytest -p no:cacheprovider tests/test_v189_classification_production.py -q -k 'stream or range or cleanup or mutation or symlink'\`. - Full \`tests/test_v189_classification_production.py\`, classification contract   suites, direct parser/route probes, and the existing replacement callbacks   with \`raising=True\`. - \`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend .venv/bin/python -m compileall -q backend/workbench/http/runs_routes.py backend/workbench/repository/file_integrity.py\`. - \`git diff --check 1a910c6c83d5d57b35d37031ca84b5d8b15b3255..HEAD\`. - Formal \`verify\` and CLI-generated \`retrospective\`, with \`unresolved=0\`.  ## Known gates  Inherited rem16 fixture/environment gates remain explicit \`NOT VERIFIED\` unless rerun in this line: \`tests/test_api.py -q -k artifacts\` (remediation-15 recorded 2 failed, 6 passed, 31 deselected, 1 warning), \`tests/predictive_research/test_consumer_projection_v186.py\` (1 failed, 3 passed), and \`tests/test_v189_artifact_integrity.py\` (3 failed, 1 warning). Central Agent/Notebook/Report, browser-visible acceptance, external provider, host/full gate, performance, release, merge, push, and tag verification remain \`NOT VERIFIED\`.

## Final status

COMPLETED

## Metrics

- Failure frequency: 3/12 (25.0%; 25.0 per 100 events)
- Repeat rate: 1/3 (33.3%)
- Recurrence rate: 1/2 (50.0%)
- MTTR: median=234000 ms (sample=3; unresolved=0)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/7 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-20T04:27:21.000Z `range_semantics_red`; cause_status: `known`; cause: The Workbench-owned parser accepted signed numeric syntax, silently discarded malformed range components, and raised unsatisfiable for a mixed set instead of applying byte-range-set semantics.; resolution: `open`; lesson: Validate the complete range-set grammar before satisfiability filtering, then return 416 only when every syntactically valid component is unsatisfiable.

## All errors

- #3 2026-08-20T04:29:30.000Z `decimal_conversion_red`; cause_status: `known`; cause: The strict digit check still allowed a bounded-header 5000-digit numeric component to escape as a raw ValueError from int conversion instead of the parser's malformed-range error.; resolution: `open`; lesson: Translate bounded decimal-conversion failures into the same explicit malformed-range 400 boundary rather than leaking a generic ValueError.
- #4 2026-08-20T04:30:22.000Z `formal_event_redaction_retry`; cause_status: `known`; cause: The first attempt to append the decimal RED evidence was rejected by the formal event redaction guard because its free-text wording matched the sensitive-pattern filter.; resolution: `resolved`; lesson: Keep formal event free text diagnostic and validator-safe; verify the append result before deleting the repository-relative event source.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `formal-event-redaction-retry`: occurrences=1; cause_status: `known`; root cause: The first attempt to append the decimal RED evidence was rejected by the formal event redaction guard because its free-text wording matched the sensitive-pattern filter.; solution: `resolved`
- `range-parser-strictness`: occurrences=2; cause_status: `known`; root cause: The Workbench-owned parser accepted signed numeric syntax, silently discarded malformed range components, and raised unsatisfiable for a mixed set instead of applying byte-range-set semantics.; solution: `open`

## Added tests

- `tests/predictive_research/test_classification_contracts_v189.py`
- `tests/test_v189_classification_production.py`

## New rules

- `formal-event-redaction-retry`: line experience occurrence(s)=1
- `range-parser-strictness`: line experience occurrence(s)=2

## Future guidance

- Keep formal event free text diagnostic and validator-safe; verify the append result before deleting the repository-relative event source.
- Translate bounded decimal-conversion failures into the same explicit malformed-range 400 boundary rather than leaking a generic ValueError.
- Validate the complete range-set grammar before satisfiability filtering, then return 416 only when every syntactically valid component is unsatisfiable.

## Event index

- #1: `ca185dfc-c4d5-4422-a0f9-911fcb8d7d65` | 2026-08-20T04:26:04.828Z | STATE_CHANGE/line_started | incident=`0eb6a938-65b6-4013-a014-3f0c6c0881e9` | lesson_key=`frozen-context-before-start` | event_sha256=`e945d992dae7ecf542a73240994c5904838c492915845eadcd1c562167c9822e`
- #2: `fdf1e3cc-72a3-4697-99bf-afc6b2742fdd` | 2026-08-20T04:27:21.000Z | FAILURE/range_semantics_red | incident=`fdf1e3cc-72a3-4697-99bf-afc6b2742fdd` | lesson_key=`range-parser-strictness` | event_sha256=`10bcdcb7b7d92515c013360487c7d4957b32e8f6fd7b10b9fe7930cb0af129c2`
- #3: `219c5e97-f167-4b08-a4d1-d717767fe588` | 2026-08-20T04:29:30.000Z | ERROR/decimal_conversion_red | incident=`219c5e97-f167-4b08-a4d1-d717767fe588` | lesson_key=`range-parser-strictness` | event_sha256=`e16425f2b463af6b777744ece55a121cfda6eb21ca1336f968774b6fe1a7b189`
- #4: `e39a1a01-b9bf-4497-bd7b-5e0e401a18da` | 2026-08-20T04:30:22.000Z | ERROR/formal_event_redaction_retry | incident=`e39a1a01-b9bf-4497-bd7b-5e0e401a18da` | lesson_key=`formal-event-redaction-retry` | event_sha256=`cfd957aa75372a03a008b56dcec572c398b9637db532c94ca122c6a0e0f9d7ad`
- #5: `5ba2ee28-0af6-48ed-8893-661ffa3d9903` | 2026-08-20T04:33:23.000Z | GATE/range_semantics_red_resolved | incident=`fdf1e3cc-72a3-4697-99bf-afc6b2742fdd` | lesson_key=`range-parser-strictness` | event_sha256=`608941511f433e9f68360600e3e112678dae06e41b82723939bac7b93dec807b`
- #6: `c999089a-4e4e-4ea2-a902-a1347975e442` | 2026-08-20T04:33:24.000Z | GATE/decimal_conversion_red_resolved | incident=`219c5e97-f167-4b08-a4d1-d717767fe588` | lesson_key=`range-parser-strictness` | event_sha256=`bc5e35512df6c5d73981589cbc1e97937a90e68164c3e9a08e428e4e2f27277e`
- #7: `c20098cd-a74a-428a-84a4-a944bd14d23d` | 2026-08-20T04:33:25.000Z | GATE/focused_range_green | incident=`c20098cd-a74a-428a-84a4-a944bd14d23d` | lesson_key=`range-rfc-satisfiability` | event_sha256=`ceb3aa742cfbb515f1070b48e70b29fb29ab39c964ea56fb6c818f2a874c72a4`
- #8: `7bf3344f-0c8e-4edd-abae-15354fd140ca` | 2026-08-20T04:33:26.000Z | GATE/production_suite_green | incident=`7bf3344f-0c8e-4edd-abae-15354fd140ca` | lesson_key=`classification-production-suite` | event_sha256=`608e871a1aaa98db2b14dc1743902db96bb488ea8ea13b362741183ddbd10cf5`
- #9: `55942aa5-84a5-41b0-b855-aa44358ae1a1` | 2026-08-20T04:33:27.000Z | GATE/classification_contracts_green | incident=`55942aa5-84a5-41b0-b855-aa44358ae1a1` | lesson_key=`classification-contract-boundary` | event_sha256=`babb5d278de93dacdd26c34c097eac09507e235f0ff9ee96ed9ac16ec5b17e2a`
- #10: `37c2ed16-a81b-42b0-a988-fdbd010b7931` | 2026-08-20T04:33:28.000Z | GATE/direct_compile_green | incident=`37c2ed16-a81b-42b0-a988-fdbd010b7931` | lesson_key=`classification-static-integrity` | event_sha256=`678860a09aafdde6c6ab16cff83a7dcc8207e6a3de5f32f42e866e6499790c2e`
- #11: `6fd6ec7e-88d8-4e6a-94a7-3e0b65c7b1f9` | 2026-08-20T04:37:35.000Z | GATE/baseline_diff_check_green | incident=`6fd6ec7e-88d8-4e6a-94a7-3e0b65c7b1f9` | lesson_key=`classification-static-integrity` | event_sha256=`c0796218c51b45307d73338596b0d9cee8e58e2801b93c4eb71835872bc14fae`
- #12: `b54ee2c1-2abf-4e5f-aeb4-431bd6810e3e` | 2026-08-20T04:38:18.000Z | STATE_CHANGE/remediation_17_completed | incident=`b54ee2c1-2abf-4e5f-aeb4-431bd6810e3e` | lesson_key=`remediation-17-formal-closeout` | event_sha256=`a69804a9e73d05e3ba2adb0b68e6cb41f1645f296e7774cdefd55e257f21b73e`
