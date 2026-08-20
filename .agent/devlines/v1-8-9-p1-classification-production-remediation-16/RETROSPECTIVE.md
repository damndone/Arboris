# Retrospective — v1-8-9-p1-classification-production-remediation-16

## Goal

# Workbench v1.8.9 P1 classification production remediation-16 objective  - Exact baseline: \`b57cc22de59f55cee9e349360dae281f7b3016cf\`. - Formal line: \`v1-8-9-p1-classification-production-remediation-16\`. - Scope: close the independent quality-review P1 in the classification-owned   generic artifact download path without changing central Agent, Notebook, or   Report behavior.  ## Required outcome  1. Replace the generic artifact route's private Starlette    \`FileResponse._parse_range_header\` call with a Workbench-owned bounded Range    parser. Preserve single-range and multipart-range behavior, \`If-Range\`,    \`400\`/\`416\` boundaries, compatibility headers, the 64 KiB stream chunk and    512 MiB size policy, same-FD reads, cleanup, and read-time TOCTOU checks. 2. Add regression coverage for \`os.pread\` failure, iterator failure,    inode/device replacement, and \`Last-Modified\`/\`If-Range\` behavior. Keep    replacement callbacks \`raising=True\` and execute the direct probes. 3. Produce exact formal evidence and a new implementation/formal-closeout    handoff. Do not edit remediation-15 events, Context Pack, or retrospective.  ## Allowed paths  - \`backend/workbench/http/runs_routes.py\` - \`tests/test_v189_classification_production.py\` - \`docs/superpowers/objectives/2026-08-20-v1.8.9-p1-classification-production-remediation-16-objective.md\` - \`docs/superpowers/plans/2026-08-20-v1.8.9-p1-classification-production-remediation-16.md\` - \`docs/superpowers/handoff/2026-08-20-v1.8.9-p1-classification-production-remediation-16-handoff.md\` - \`.agent/devlines/v1-8-9-p1-classification-production-remediation-16/**\` (only   through \`scripts/devline_control.py\`).  ## Protected boundaries  - \`backend/workbench/predictive_research/consumer_projection.py\` and the   remediation-15 whole-body \`consumer_projection\` residual are out of scope. - Central Agent, Notebook, and Report consumers and their tests are out of   scope. - Existing remediation-15 formal events, manifest, Context Pack, and   retrospective are immutable.  ## Verification contract  - \`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend .venv/bin/python -m pytest -p no:cacheprovider tests/test_v189_classification_production.py -q -k 'stream or range or cleanup or mutation or symlink'\` - \`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend .venv/bin/python -m pytest -p no:cacheprovider tests/test_v189_classification_production.py -q\` - Relevant classification contract/production tests, direct probes, and   \`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend .venv/bin/python -m compileall -q backend/workbench/http/runs_routes.py backend/workbench/repository/file_integrity.py\`. - \`git diff --check b57cc22de59f55cee9e349360dae281f7b3016cf..HEAD\`. - Formal verify and retrospective through \`scripts/devline_control.py\`.  ## Known gates  Inherited fixture and environment gates remain explicit \`NOT VERIFIED\` unless rerun in this line: \`tests/test_api.py -q -k artifacts\` (remediation-15 had 2 failed, 6 passed, 31 deselected, 1 warning), \`tests/predictive_research/test_consumer_projection_v186.py\` (remediation-15 had 1 failed, 3 passed), and \`tests/test_v189_artifact_integrity.py\` (remediation-15 had 3 failed, 1 warning). Central Agent/Notebook/Report, browser-visible acceptance, external provider calls, host gate/full gate, performance, release, merge, push, and tag verification remain \`NOT VERIFIED\`.

## Final status

COMPLETED

## Metrics

- Failure frequency: 2/10 (20.0%; 20.0 per 100 events)
- Repeat rate: 0/2 (0.0%)
- Recurrence rate: 0/2 (0.0%)
- MTTR: median=130500 ms (sample=2; unresolved=0)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/6 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-20T04:00:06.000Z `range_parser_red`; cause_status: `known`; cause: The generic artifact route still called Starlette's private FileResponse range parser, and the new Workbench-owned bounded parser was not present.; resolution: `open`; lesson: Make the generic route's Range compatibility seam Workbench-owned and bounded before claiming the private framework dependency is removed.

## All errors

- #8 2026-08-20T04:08:22.000Z `plan_trailing_whitespace`; cause_status: `known`; cause: The first staged implementation diff check found Markdown hard-break whitespace in the new rem16 plan.; resolution: `resolved`; lesson: Run diff-check against staged new documentation, not only tracked working-tree paths that omit untracked files.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `artifact-range-compatibility`: occurrences=1; cause_status: `known`; root cause: The generic artifact route still called Starlette's private FileResponse range parser, and the new Workbench-owned bounded parser was not present.; solution: `open`
- `classification-static-integrity`: occurrences=1; cause_status: `known`; root cause: The first staged implementation diff check found Markdown hard-break whitespace in the new rem16 plan.; solution: `resolved`

## Added tests

- `tests/predictive_research/test_classification_contracts_v189.py`
- `tests/test_v189_classification_production.py`

## New rules

- `artifact-range-compatibility`: line experience occurrence(s)=1
- `classification-static-integrity`: line experience occurrence(s)=1

## Future guidance

- Make the generic route's Range compatibility seam Workbench-owned and bounded before claiming the private framework dependency is removed.
- Run diff-check against staged new documentation, not only tracked working-tree paths that omit untracked files.

## Event index

- #1: `43125406-d407-49ae-8561-addcf5f1c87d` | 2026-08-20T03:57:54.058Z | STATE_CHANGE/line_started | incident=`13eb5f41-64f7-43d6-8f78-9246b3624582` | lesson_key=`frozen-context-before-start` | event_sha256=`f06f4d853f9728f7ffa1edf8ebaf25cf3e478799ab13047f0bd59e1586a56e80`
- #2: `b0d4fb1f-7656-44c5-9014-004cb568985e` | 2026-08-20T04:00:06.000Z | FAILURE/range_parser_red | incident=`b0d4fb1f-7656-44c5-9014-004cb568985e` | lesson_key=`artifact-range-compatibility` | event_sha256=`2f428ef058c28ae9645db3a0b3081ad89bea9a9e1cf90430d3d958276fa0b104`
- #3: `c1a4e7f2-4c55-4d3f-8d15-7b0b9e1a6420` | 2026-08-20T04:04:27.000Z | GATE/range_parser_red_resolved | incident=`b0d4fb1f-7656-44c5-9014-004cb568985e` | lesson_key=`artifact-range-compatibility` | event_sha256=`b2748697b49cfb208f1a1444276a8c2ce9a4e26cc23f33f8a19c9a281873847e`
- #4: `c2b5f803-5d66-4e40-9e26-8c1c0f2b7531` | 2026-08-20T04:04:28.000Z | GATE/production_suite_green | incident=`c2b5f803-5d66-4e40-9e26-8c1c0f2b7531` | lesson_key=`classification-production-suite` | event_sha256=`b3da15d6c7a157e313409be8ade3255468c52442e758480dd5f3933be62eb336`
- #5: `c3c6a914-6e77-4f51-af37-9d2d1a3c8642` | 2026-08-20T04:04:29.000Z | GATE/classification_contracts_green | incident=`c3c6a914-6e77-4f51-af37-9d2d1a3c8642` | lesson_key=`classification-contract-boundary` | event_sha256=`401fef551c6dd014cc0ac52564544ada0d2e155d020dc75c3271317436187ac6`
- #6: `c4d7ba25-7f88-4062-b048-ae3e2b4d9753` | 2026-08-20T04:04:30.000Z | GATE/direct_probes_green | incident=`c4d7ba25-7f88-4062-b048-ae3e2b4d9753` | lesson_key=`artifact-fd-cleanup` | event_sha256=`710b01039d25ebda1f2787e1a1ff704bde118f30133545f90a040a5b59ba014e`
- #7: `c5e8cb36-8099-4173-c159-bf4f3c5ea864` | 2026-08-20T04:04:31.000Z | GATE/compile_static_green | incident=`c5e8cb36-8099-4173-c159-bf4f3c5ea864` | lesson_key=`classification-static-integrity` | event_sha256=`e78c970a2cc4f6abcc5d814e410acc8161b55238d72bbf5258940b9f130bad91`
- #8: `5c483959-1d17-4cb1-9a30-0c6752ae02a9` | 2026-08-20T04:08:22.000Z | ERROR/plan_trailing_whitespace | incident=`5c483959-1d17-4cb1-9a30-0c6752ae02a9` | lesson_key=`classification-static-integrity` | event_sha256=`822709d82ab6a489a21f24199dbe0f601146db68f7573ab666f969e1dda3a074`
- #9: `2c6b206e-7e9e-4875-b41e-141df924bd1e` | 2026-08-20T04:09:32.000Z | GATE/baseline_diff_check_green | incident=`2c6b206e-7e9e-4875-b41e-141df924bd1e` | lesson_key=`classification-static-integrity` | event_sha256=`139e80a2b7e7053f6329227572e0c1b36423c3ff9ded0270fe46c8fab615ce3b`
- #10: `9c5f6120-fcf8-4e48-b49b-86999f613603` | 2026-08-20T04:09:56.000Z | STATE_CHANGE/remediation_16_completed | incident=`9c5f6120-fcf8-4e48-b49b-86999f613603` | lesson_key=`remediation-16-formal-closeout` | event_sha256=`8b0406eeef4a06a4f0487efac9f3b0bf8952ae84aadc447e9bced3a9c773c3ea`
